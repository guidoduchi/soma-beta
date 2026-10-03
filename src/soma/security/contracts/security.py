from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunControlContextV1:
    run_id: str
    data_instance_id: str
    authenticated: bool = True
    source: str = "loopback-direct-no-proxy"


@dataclass(frozen=True, slots=True)
class CipherVerificationV1:
    cipher_version: str
    provider: str
    page_size: int = 4096
    use_hmac: bool = True
    plaintext_header_size: int = 0
    foreign_keys: bool = True
    integrity_probe: str = "pass"
