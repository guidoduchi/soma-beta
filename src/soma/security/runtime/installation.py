"""Source installation security assembly; Foundation retains instance ownership."""
from pathlib import Path

from soma.foundation.errors import SecurityNotReady
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.security.auth.sessions import SessionSecurityProvider
from soma.security.crypto.dpapi import WindowsDpapiProvider
from soma.security.crypto.live_key import LiveDataKeyProvider
from soma.security.crypto.sqlcipher_provider import SqlCipherConnectionSecurityProvider
from soma.security.runtime.control import RunControlProvider, publish_owned_file, read_owned_file
from soma.security.runtime.windows import WindowsAclProvider, local_app_data, reject_redirects


def canonical_source_instance():
    return reject_redirects(local_app_data() / "SOMA" / "Beta" / "instance-v1")


def prepare_instance_directories(root, files):
    root = reject_redirects(Path(root))
    # Known-folder parents exist; create each missing SOMA component securely.
    missing = []
    current = root
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        files.ensure_owner_only_directory(directory)
    files.verify(root)
    for name in ("data", "security", "runtime", "diagnostics"):
        files.ensure_owner_only_directory(root / name)


def read_installation_id(root, files):
    path = Path(root) / "security" / "installation-id"
    if not path.exists():
        return None
    value = read_owned_file(path, files, limit=37)
    try:
        if len(value) != 37 or value[-1:] != b"\n":
            raise ValueError
        return require_uuid4(value[:-1].decode("ascii"))
    except (ValueError, UnicodeError):
        raise SecurityNotReady("installation identity is invalid") from None


class SourceInstallationSecurity:
    """Compose declared key/control/session interfaces without new lifecycle authority."""
    def __init__(self, root):
        self.root = reject_redirects(Path(root))
        self.file_security = WindowsAclProvider()
        self.dpapi = WindowsDpapiProvider()
        self.installation_id = None
        self.cipher, self.control, self.sessions = None, None, None
        self.ownership = lambda: False

    def prepare_storage(self, ownership_assertion):
        if not ownership_assertion():
            raise SecurityNotReady("storage preparation requires Foundation ownership")
        self.ownership = ownership_assertion
        identifier = read_installation_id(self.root, self.file_security)
        if identifier is None:
            if (self.root / "data" / "soma.db").exists() or (self.root / "security" / "live-data-key.dpapi").exists():
                raise SecurityNotReady("existing protected data has no installation identity")
            identifier = new_uuid4()
            publish_owned_file(self.root / "security" / "installation-id", (identifier + "\n").encode("ascii"), self.file_security)
        self.installation_id = identifier
        key = LiveDataKeyProvider(self.root, identifier, ownership_assertion=ownership_assertion,
            file_security=self.file_security, dpapi=self.dpapi)
        key.prepare()
        self.cipher = SqlCipherConnectionSecurityProvider(key)
        self.control = RunControlProvider(self.root / "runtime", identifier, file_security=self.file_security, dpapi=self.dpapi)

    def acquire_live_dek_handle(self):
        if self.cipher is None:
            raise SecurityNotReady("storage security is not prepared")
        return self.cipher.acquire_live_dek_handle()

    def key_connection(self, connection, key):
        return self.cipher.key_connection(connection, key)

    def verify_cipher_connection(self, connection):
        return self.cipher.verify_cipher_connection(connection)

    def prepare_run(self, **values):
        locator = self.control.prepare_run(**values)
        self.sessions = SessionSecurityProvider(values["run_id"], values["readiness_locator"])
        return locator

    def close_run(self, **values):
        if self.sessions is not None:
            self.sessions.invalidate_all("host stopped")
        if self.control is not None:
            self.control.close_run(**values)

    def authenticate_control_request(self, headers, expected_run_id):
        return self.control.authenticate_control_request(headers, expected_run_id)

    def validate_request(self, request, *, mutation):
        if self.sessions is None:
            raise SecurityNotReady("browser security is not prepared")
        return self.sessions.validate_request(request, mutation=mutation)

    def self_health(self, expected):
        return self.control.self_health(expected)
