"""Native Windows trust adapters. No shell, environment-folder or PID heuristics."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from soma.foundation.errors import SecurityNotReady


def api(dll, name, result, arguments):
    if os.name != "nt":
        raise SecurityNotReady("Windows security provider requires Windows")
    function = getattr(C.WinDLL(dll, use_last_error=True), name)
    function.restype = result
    function.argtypes = arguments
    return function


def checked(result):
    if not result:
        raise SecurityNotReady("Windows security operation failed")
    return result


def local_free(pointer):
    if pointer:
        api("kernel32", "LocalFree", C.c_void_p, [C.c_void_p])(pointer)


def reject_redirects(path: Path):
    candidate = Path(path)
    if not candidate.is_absolute():
        raise SecurityNotReady("security path must be absolute")
    for item in (candidate, *candidate.parents):
        try:
            metadata = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise SecurityNotReady("security path contains a redirected component")
    return candidate


def current_user_sid() -> str:
    token = W.HANDLE()
    process = api("kernel32", "GetCurrentProcess", W.HANDLE, [])()
    checked(api("advapi32", "OpenProcessToken", W.BOOL, [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)])(process, 8, C.byref(token)))
    try:
        size = W.DWORD()
        query = api("advapi32", "GetTokenInformation", W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)])
        query(token, 1, None, 0, C.byref(size))
        if not 0 < size.value <= 65536:
            raise SecurityNotReady("Windows token size is invalid")
        buffer = C.create_string_buffer(size.value)
        checked(query(token, 1, buffer, size, C.byref(size)))
        return sid_string(C.cast(buffer, C.POINTER(C.c_void_p))[0])
    finally:
        api("kernel32", "CloseHandle", W.BOOL, [W.HANDLE])(token)


def sid_string(pointer) -> str:
    result = W.LPWSTR()
    checked(api("advapi32", "ConvertSidToStringSidW", W.BOOL, [C.c_void_p, C.POINTER(W.LPWSTR)])(pointer, C.byref(result)))
    try:
        return result.value
    finally:
        local_free(C.cast(result, C.c_void_p))


class SecurityAttributes(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class WindowsAclProvider:
    def __init__(self):
        self.sid = current_user_sid()

    def _descriptor(self, directory):
        flags = "OICI" if directory else ""
        sddl = f"O:{self.sid}D:P(A;{flags};FA;;;{self.sid})(A;{flags};FA;;;SY)"
        descriptor = C.c_void_p()
        checked(api("advapi32", "ConvertStringSecurityDescriptorToSecurityDescriptorW", W.BOOL, [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p])(sddl, 1, C.byref(descriptor), None))
        return descriptor

    def verify(self, path):
        target = reject_redirects(Path(path))
        owner, dacl, descriptor = C.c_void_p(), C.c_void_p(), C.c_void_p()
        result = api("advapi32", "GetNamedSecurityInfoW", W.DWORD, [W.LPCWSTR, C.c_int, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p)])(str(target), 1, 5, C.byref(owner), None, C.byref(dacl), None, C.byref(descriptor))
        if result:
            raise SecurityNotReady("security path ACL cannot be read")
        try:
            control, revision = W.WORD(), W.DWORD()
            checked(api("advapi32", "GetSecurityDescriptorControl", W.BOOL, [C.c_void_p, C.POINTER(W.WORD), C.POINTER(W.DWORD)])(descriptor, C.byref(control), C.byref(revision)))
            if sid_string(owner) != self.sid or not control.value & 0x1000 or not dacl.value:
                raise SecurityNotReady("security path owner/inheritance is unsafe")
            # ACL header is eight bytes, with WORD AceCount at offset four.
            count = C.c_ushort.from_address(dacl.value + 4).value
            if count != 2:
                raise SecurityNotReady("security path must grant only user and SYSTEM")
            principals = set()
            for index in range(count):
                ace = C.c_void_p()
                checked(api("advapi32", "GetAce", W.BOOL, [C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)])(dacl, index, C.byref(ace)))
                kind = C.c_ubyte.from_address(ace.value).value
                flags = C.c_ubyte.from_address(ace.value + 1).value
                mask = C.c_uint32.from_address(ace.value + 4).value
                if kind != 0 or flags & ~3 or mask != 0x1F01FF:
                    raise SecurityNotReady("security path ACE is unsafe")
                principals.add(sid_string(ace.value + 8))
            if principals != {self.sid, "S-1-5-18"}:
                raise SecurityNotReady("security path principals are unsafe")
        finally:
            local_free(descriptor)

    def ensure_owner_only_directory(self, path):
        target = reject_redirects(Path(path))
        if not target.exists():
            descriptor = self._descriptor(True)
            try:
                attributes = SecurityAttributes(C.sizeof(SecurityAttributes), descriptor, False)
                result = api("kernel32", "CreateDirectoryW", W.BOOL, [W.LPCWSTR, C.POINTER(SecurityAttributes)])(str(target), C.byref(attributes))
                if not result and C.get_last_error() != 183:
                    checked(result)
            finally:
                local_free(descriptor)
        if not target.is_dir():
            raise SecurityNotReady("security directory is invalid")
        self.verify(target)

    def ensure_owner_only_file(self, path):
        # Existing files are checked, never silently re-ACL'd into trusted state.
        if not Path(path).is_file():
            raise SecurityNotReady("security file is unavailable")
        self.verify(path)

    def create_file(self, path):
        import msvcrt
        target = reject_redirects(Path(path))
        self.verify(target.parent)
        descriptor = self._descriptor(False)
        try:
            attributes = SecurityAttributes(C.sizeof(SecurityAttributes), descriptor, False)
            handle = api("kernel32", "CreateFileW", W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(SecurityAttributes), W.DWORD, W.DWORD, W.HANDLE])(str(target), 0x40000000, 0, C.byref(attributes), 1, 0x80, None)
            if handle == C.c_void_p(-1).value:
                raise SecurityNotReady("owner-only file creation failed")
            try:
                descriptor_number = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            except BaseException:
                api("kernel32", "CloseHandle", W.BOOL, [W.HANDLE])(handle)
                raise
            return os.fdopen(descriptor_number, "wb")
        finally:
            local_free(descriptor)

    def remove_exact_file(self, path, expected_bytes):
        """Delete the retained file object, never a replacement at its path."""
        target = reject_redirects(Path(path))
        self.verify(target.parent)
        if not target.exists():
            return False
        self.ensure_owner_only_file(target)
        handle = api("kernel32", "CreateFileW", W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE])(
            str(target), 0x80010000, 1, None, 3, 0x00200000, None)  # READ+DELETE, share-read, open-reparse-point
        if handle == C.c_void_p(-1).value:
            raise SecurityNotReady("exact-owned file cleanup could not retain its identity")
        class FileInformation(C.Structure):
            _fields_ = [("attributes", W.DWORD), ("created", W.FILETIME), ("accessed", W.FILETIME), ("written", W.FILETIME),
                ("volume", W.DWORD), ("size_high", W.DWORD), ("size_low", W.DWORD), ("links", W.DWORD), ("index_high", W.DWORD), ("index_low", W.DWORD)]
        try:
            information = FileInformation()
            checked(api("kernel32", "GetFileInformationByHandle", W.BOOL, [W.HANDLE, C.POINTER(FileInformation)])(handle, C.byref(information)))
            if information.attributes & (0x400 | 0x10) or information.links != 1:
                raise SecurityNotReady("exact-owned cleanup file is redirected or linked")
            if (information.size_high << 32) | information.size_low != len(expected_bytes):
                return False
            captured = C.create_string_buffer(len(expected_bytes) + 1)
            size = W.DWORD()
            checked(api("kernel32", "ReadFile", W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p])(
                handle, captured, len(expected_bytes) + 1, C.byref(size), None))
            if captured.raw[:size.value] != expected_bytes:
                return False
            self.ensure_owner_only_file(target)
            disposition = C.c_ubyte(1)
            checked(api("kernel32", "SetFileInformationByHandle", W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD])(
                handle, 4, C.byref(disposition), C.sizeof(disposition)))
            return True
        finally:
            api("kernel32", "CloseHandle", W.BOOL, [W.HANDLE])(handle)


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    process_birth_id: str
    image: Path


def process_identity(pid: int) -> ProcessIdentity:
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise SecurityNotReady("process PID is invalid")
    handle = api("kernel32", "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])(0x101000, False, pid)
    checked(handle)
    try:
        if api("kernel32", "WaitForSingleObject", W.DWORD, [W.HANDLE, W.DWORD])(handle, 0) != 258:
            raise SecurityNotReady("host process is not live")
        times = [W.FILETIME() for _ in range(4)]
        checked(api("kernel32", "GetProcessTimes", W.BOOL, [W.HANDLE, *[C.POINTER(W.FILETIME)] * 4])(handle, *[C.byref(item) for item in times]))
        size = W.DWORD(32768)
        image = C.create_unicode_buffer(size.value)
        checked(api("kernel32", "QueryFullProcessImageNameW", W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])(handle, 0, image, C.byref(size)))
        birth = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ProcessIdentity(pid, str(birth), Path(image.value).resolve(strict=True))
    finally:
        api("kernel32", "CloseHandle", W.BOOL, [W.HANDLE])(handle)


def local_app_data() -> Path:
    import uuid
    class Guid(C.Structure):
        _fields_ = [("bytes", C.c_ubyte * 16)]
    folder = Guid((C.c_ubyte * 16).from_buffer_copy(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le))
    result = W.LPWSTR()
    status = api("shell32", "SHGetKnownFolderPath", C.c_long, [C.POINTER(Guid), W.DWORD, W.HANDLE, C.POINTER(W.LPWSTR)])(C.byref(folder), 0, None, C.byref(result))
    try:
        if status != 0 or not result:
            raise SecurityNotReady("Windows known-folder resolution failed")
        return reject_redirects(Path(result.value)).resolve(strict=True)
    finally:
        if result:
            api("ole32", "CoTaskMemFree", None, [C.c_void_p])(C.cast(result, C.c_void_p))


class VerifiedProcessWait:
    """Retain an exact verified process handle before sending shutdown."""
    def __init__(self, identity):
        self.handle = api("kernel32", "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])(0x101000, False, identity.pid)
        checked(self.handle)
        try:
            times = [W.FILETIME() for _ in range(4)]
            checked(api("kernel32", "GetProcessTimes", W.BOOL, [W.HANDLE, *[C.POINTER(W.FILETIME)] * 4])(self.handle, *[C.byref(item) for item in times]))
            birth = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
            size = W.DWORD(32768)
            image = C.create_unicode_buffer(size.value)
            checked(api("kernel32", "QueryFullProcessImageNameW", W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])(self.handle, 0, image, C.byref(size)))
            if birth != identity.process_birth_id or Path(image.value).resolve(strict=True) != identity.image:
                raise SecurityNotReady("shutdown process identity changed")
        except BaseException:
            self.close()
            raise

    def wait(self, seconds):
        result = api("kernel32", "WaitForSingleObject", W.DWORD, [W.HANDLE, W.DWORD])(self.handle, max(0, int(seconds * 1000)))
        if result not in {0, 258}:
            raise SecurityNotReady("shutdown process wait failed")
        return result == 0

    def close(self):
        if self.handle:
            api("kernel32", "CloseHandle", W.BOOL, [W.HANDLE])(self.handle)
            self.handle = None


def open_verified_origin(origin):
    from soma.foundation.runtime.registry import _ORIGIN
    match = _ORIGIN.fullmatch(origin)
    if match is None or int(match[1]) > 65535:
        raise SecurityNotReady("browser origin is invalid")
    result = api("shell32", "ShellExecuteW", C.c_void_p, [W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_int])(None, "open", origin, None, None, 1)
    if not result or result <= 32:
        raise SecurityNotReady("verified browser activation failed")
