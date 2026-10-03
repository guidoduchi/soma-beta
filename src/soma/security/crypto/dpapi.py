"""CurrentUser DPAPI with framed purpose/installation binding and bounded inputs."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import struct
import uuid

from soma.foundation.errors import SecurityNotReady
from soma.foundation.identifiers import require_uuid4
from soma.security.runtime.windows import api, local_free

_MAGICS = {"live_data_dek": b"SOMA-DPAPI-KEY-V1\0", "run_control": b"SOMA-DPAPI-RUN-V1\0", "admin_password_reset": b"SOMA-DPAPI-RESET-V1\0"}
_PURPOSES = {"live_data_dek": 32, "run_control": 32, "admin_password_reset": 32}
_MAX_BLOB = 65536


class Blob(C.Structure):
    _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]


def _blob(value):
    buffer = (C.c_ubyte * len(value)).from_buffer_copy(value)
    return buffer, Blob(len(value), buffer)


class WindowsDpapiProvider:
    def _binding(self, purpose, installation_id):
        require_uuid4(installation_id)
        if purpose not in _PURPOSES:
            raise SecurityNotReady("unsupported DPAPI purpose")
        return hashlib.sha256(f"SOMA-BETA-DPAPI-V1\0{purpose}\0{installation_id}".encode("utf-8")).digest()

    def _crypt(self, value, purpose, installation_id, *, protect):
        entropy = self._binding(purpose, installation_id)
        input_buffer, input_blob = _blob(value)
        entropy_buffer, entropy_blob = _blob(entropy)
        output = Blob()
        try:
            if protect:
                function = api("crypt32", "CryptProtectData", W.BOOL, [C.POINTER(Blob), W.LPCWSTR, C.POINTER(Blob), C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Blob)])
                result = function(C.byref(input_blob), f"SOMA {purpose}", C.byref(entropy_blob), None, None, 1, C.byref(output))
            else:
                function = api("crypt32", "CryptUnprotectData", W.BOOL, [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Blob)])
                result = function(C.byref(input_blob), None, C.byref(entropy_blob), None, None, 1, C.byref(output))
            if not result or not 0 < output.size <= _MAX_BLOB:
                raise SecurityNotReady("DPAPI protection/unwrap failed")
            return C.string_at(output.data, output.size)
        finally:
            C.memset(input_buffer, 0, len(input_buffer))
            C.memset(entropy_buffer, 0, len(entropy_buffer))
            if output.data:
                C.memset(output.data, 0, output.size)
                local_free(output.data)

    def protect_current_user(self, plaintext, purpose, installation_id):
        self._binding(purpose, installation_id)
        if not isinstance(plaintext, (bytes, bytearray)) or len(plaintext) != _PURPOSES[purpose]:
            raise SecurityNotReady("DPAPI secret length is invalid")
        encrypted = self._crypt(plaintext, purpose, installation_id, protect=True)
        purpose_bytes = purpose.encode("ascii")
        return _MAGICS[purpose] + bytes([len(purpose_bytes)]) + purpose_bytes + uuid.UUID(installation_id).bytes + struct.pack(">I", len(encrypted)) + encrypted

    def unprotect_current_user(self, blob, purpose, installation_id):
        self._binding(purpose, installation_id)
        magic = _MAGICS[purpose]
        try:
            if not isinstance(blob, bytes) or not len(magic) + 22 <= len(blob) <= _MAX_BLOB + 128 or not blob.startswith(magic):
                raise ValueError
            offset = len(magic)
            length = blob[offset]
            offset += 1
            bound_purpose = blob[offset:offset + length].decode("ascii")
            offset += length
            bound_id = str(uuid.UUID(bytes=blob[offset:offset + 16]))
            offset += 16
            size = struct.unpack(">I", blob[offset:offset + 4])[0]
            offset += 4
            if bound_purpose != purpose or bound_id != installation_id or not 0 < size <= _MAX_BLOB or len(blob) != offset + size:
                raise ValueError
        except (ValueError, UnicodeError, struct.error):
            raise SecurityNotReady("DPAPI envelope binding/shape is invalid") from None
        secret = self._crypt(blob[offset:], purpose, installation_id, protect=False)
        if len(secret) != _PURPOSES[purpose]:
            raise SecurityNotReady("DPAPI unwrapped secret length is invalid")
        return secret
