"""Accepted fixed Argon2id profile; passwords never become encryption keys."""
import secrets
from threading import Lock
import time

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import Argon2Error

from soma.foundation.errors import SomaError


class PasswordVerifierProvider:
    def __init__(self):
        self.hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
            hash_len=32, salt_len=16, type=Type.ID, encoding="utf-8")

    @staticmethod
    def password_bytes(password):
        try:
            if not isinstance(password, str) or len(password) < 12:
                raise ValueError
            encoded = password.encode("utf-8", errors="strict")
            if len(encoded) > 1024:
                raise ValueError
            return encoded
        except (ValueError, UnicodeError):
            raise SomaError("AUTH_PASSWORD_POLICY", "password does not meet the accepted policy") from None

    def hash(self, password, confirmation):
        value = self.password_bytes(password)
        try:
            confirmed = confirmation.encode("utf-8", errors="strict") if isinstance(confirmation, str) else None
        except UnicodeError:
            confirmed = None
        if confirmed != value:
            raise SomaError("AUTH_PASSWORD_POLICY", "password confirmation differs")
        return self.hasher.hash(value, salt=secrets.token_bytes(16))

    def verify(self, verifier, password):
        try:
            value = self.password_bytes(password)
            if not isinstance(verifier, str) or not 32 <= len(verifier) <= 1024:
                return False
            parameters = extract_parameters(verifier)
            if (parameters.type, parameters.version, parameters.memory_cost, parameters.time_cost,
                parameters.parallelism, parameters.salt_len, parameters.hash_len) != (Type.ID, 19, 65536, 3, 4, 16, 32):
                return False
            return bool(self.hasher.verify(verifier, value))
        except (Argon2Error, ValueError, UnicodeError, SomaError):
            return False

    def check_needs_rehash(self, verifier):
        # Beta's fixed profile admits no alternate/future parameters.
        return self.hasher.check_needs_rehash(verifier)


class AuthenticationThrottle:
    """Run-local failure gate; no durable lockout or sleep inside transactions."""
    def __init__(self, *, monotonic=time.monotonic):
        self.clock = monotonic
        self.failures, self.next_allowed = 0, 0.0
        self.lock = Lock()

    def check(self):
        with self.lock:
            if self.clock() < self.next_allowed:
                raise SomaError("AUTH_RATE_LIMITED", "authentication is temporarily delayed")

    def record(self, success):
        with self.lock:
            self.failures = 0 if success else self.failures + 1
            delay = min(8, 2 ** min(3, self.failures - 5)) if self.failures >= 5 else 0
            self.next_allowed = self.clock() + delay
