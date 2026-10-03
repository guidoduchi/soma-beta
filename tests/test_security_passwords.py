import pytest
from argon2 import PasswordHasher, Type

from soma.foundation.errors import SomaError
from soma.security.auth.passwords import AuthenticationThrottle, PasswordVerifierProvider


def test_fixed_profile_and_exact_password_bytes():
    provider = PasswordVerifierProvider()
    password = "  éabcdefghijk  "
    verifier = provider.hash(password, password)
    assert verifier.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert provider.verify(verifier, password)
    assert not provider.verify(verifier, password.strip())
    assert not provider.verify(verifier, "  e\u0301abcdefghijk  ")
    assert not provider.check_needs_rehash(verifier)
    alternative = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID).hash(password)
    assert not provider.verify(alternative, password)
    assert not provider.verify("malformed verifier", password)


@pytest.mark.parametrize("password", ["short", "x" * 1025, "\ud800" * 12, None])
def test_policy_fails_without_echoing_password(password):
    provider = PasswordVerifierProvider()
    with pytest.raises(SomaError, match="AUTH_PASSWORD_POLICY"):
        provider.hash(password, password)


def test_authentication_delay_is_run_local_bounded_and_resets():
    now = [0.0]
    gate = AuthenticationThrottle(monotonic=lambda: now[0])
    for failure in range(1, 10):
        gate.check()
        gate.record(False)
        delay = min(8, 2 ** (failure - 5)) if failure >= 5 else 0
        if delay:
            with pytest.raises(SomaError, match="AUTH_RATE_LIMITED"):
                gate.check()
        now[0] += delay
    gate.check()
    gate.record(True)
    assert gate.failures == 0
    gate.check()
