"""DEK preparation requires the caller's canonical Foundation instance lock."""
from pathlib import Path
import secrets

from soma.foundation.errors import SecurityNotReady
from soma.foundation.identifiers import require_uuid4
from soma.security.crypto.dpapi import WindowsDpapiProvider
from soma.security.runtime.control import publish_owned_file, read_owned_file
from soma.security.runtime.windows import WindowsAclProvider, reject_redirects


class LiveDataKeyProvider:
    def __init__(self, instance_root, installation_id, *, ownership_assertion, file_security=None, dpapi=None):
        require_uuid4(installation_id)
        self.root = reject_redirects(Path(instance_root))
        self.installation_id = installation_id
        self.ownership = ownership_assertion
        self.files = file_security or WindowsAclProvider()
        self.dpapi = dpapi or WindowsDpapiProvider()
        self.path = self.root / "security" / "live-data-key.dpapi"

    def prepare(self):
        if not self.ownership():
            raise SecurityNotReady("live key preparation requires canonical instance ownership")
        self.files.verify(self.root)
        self.files.ensure_owner_only_directory(self.path.parent)
        if not self.path.exists():
            if (self.root / "data" / "soma.db").exists():
                raise SecurityNotReady("existing database has no protected live key")
            protected = self.dpapi.protect_current_user(secrets.token_bytes(32), "live_data_dek", self.installation_id)
            publish_owned_file(self.path, protected, self.files)
        return self.unwrap_live_dek()

    def unwrap_live_dek(self):
        captured = read_owned_file(self.path, self.files)
        value = self.dpapi.unprotect_current_user(captured, "live_data_dek", self.installation_id)
        if len(value) != 32:
            raise SecurityNotReady("live data key length is invalid")
        return value
