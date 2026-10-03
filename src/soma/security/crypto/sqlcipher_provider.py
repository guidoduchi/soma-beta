"""Strict SQLCipher connection security; never load a plaintext substitute."""
from importlib.metadata import PackageNotFoundError, version

from soma.foundation.errors import SecurityNotReady
from soma.security.contracts.security import CipherVerificationV1


class SqlCipherConnectionSecurityProvider:
    def __init__(self, live_key):
        self.live_key = live_key

    def unwrap_live_dek(self):
        return self.live_key.unwrap_live_dek()

    def acquire_live_dek_handle(self):
        # Adapter for the existing Foundation internal connection seam.
        return self.unwrap_live_dek()

    def key_connection(self, connection, key_handle):
        try:
            if version("sqlcipher3") != "0.6.2":
                raise SecurityNotReady("SQLCipher binding version mismatch")
            if not isinstance(key_handle, (bytes, bytearray)) or len(key_handle) != 32:
                raise SecurityNotReady("SQLCipher key length is invalid")
            connection.execute("PRAGMA cipher_memory_security=ON")
            connection.execute('PRAGMA key = "x\'' + key_handle.hex() + '\'"')
        except (PackageNotFoundError, SecurityNotReady):
            raise SecurityNotReady("SQLCipher binding/key provider is not ready") from None
        except Exception:
            raise SecurityNotReady("SQLCipher keying failed") from None

    def verify_cipher_connection(self, connection):
        try:
            row = connection.execute("PRAGMA cipher_version").fetchone()
            # SQLCipher exposes a version plus an edition suffix. Pin the entire
            # core version, allowing only the official edition identifiers.
            if row is None or row[0] not in {"4.17.0", "4.17.0 community", "4.17.0 enterprise"}:
                raise SecurityNotReady("SQLCipher core 4.17.0 is required")
            for name, expected in [("cipher_page_size", "4096"), ("cipher_use_hmac", "1"), ("cipher_plaintext_header_size", "0"), ("cipher_memory_security", "1"), ("cipher_hmac_algorithm", "HMAC_SHA512")]:
                value = connection.execute(f"PRAGMA {name}").fetchone()
                if value is None or str(value[0]) != expected:
                    raise SecurityNotReady("SQLCipher security profile mismatch")
            # FK policy belongs to the configured connection, before consumers.
            connection.execute("PRAGMA foreign_keys=ON")
            if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                raise SecurityNotReady("SQLCipher foreign-key policy mismatch")
            probe = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            if probe is None or type(probe[0]) is not int or probe[0] < 0:
                raise SecurityNotReady("SQLCipher schema integrity probe failed")
            return CipherVerificationV1("4.17.0", "sqlcipher3/0.6.2")
        except SecurityNotReady:
            raise
        except Exception:
            raise SecurityNotReady("SQLCipher integrity/key verification failed") from None
