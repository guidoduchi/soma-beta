"""Bounded, current-run browser sessions. Call issuance only after authentication."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import secrets
from threading import Lock
import time

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import require_uuid4
from soma.security.runtime.control import encode_secret, guard_headers

COOKIE_NAME = "soma_session"


@dataclass(frozen=True, slots=True)
class BrowserSessionV1:
    session_id: str = field(repr=False)
    csrf_token: str = field(repr=False)
    run_id: str
    actor_id: str
    issued_at_utc: int
    absolute_expires_at_utc: int

    @property
    def cookie(self):
        return f"{COOKIE_NAME}={self.session_id}; HttpOnly; SameSite=Strict; Path=/"


@dataclass(frozen=True, slots=True)
class AuthenticatedBrowserContextV1:
    actor_id: str
    run_id: str
    session_id_fingerprint: str
    origin: str


class SessionSecurityProvider:
    def __init__(self, run_id, origin, *, monotonic=time.monotonic, utc=time.time):
        require_uuid4(run_id)
        self.run_id, self.origin = run_id, origin
        self.monotonic, self.utc = monotonic, utc
        self._sessions = {}
        self._lock = Lock()

    def _expire(self, now):
        for key, (_, last_seen, absolute) in tuple(self._sessions.items()):
            if now - last_seen >= 43200 or now >= absolute:
                del self._sessions[key]

    def issue_session(self, run_id, actor_id):
        require_uuid4(actor_id)
        if run_id != self.run_id:
            raise SomaError("UNAUTHENTICATED", "browser run identity mismatch")
        with self._lock:
            now = self.monotonic()
            self._expire(now)
            if len(self._sessions) >= 4:
                raise SomaError("FORBIDDEN", "browser session capacity reached")
            session = BrowserSessionV1(encode_secret(secrets.token_bytes(32)), encode_secret(secrets.token_bytes(32)), run_id, actor_id, int(self.utc()), int(self.utc()) + 86400)
            key = hashlib.sha256(session.session_id.encode("ascii")).digest()
            self._sessions[key] = (session, now, now + 86400)
            return session

    def validate_request(self, request, *, mutation):
        headers = request.headers
        guard_headers(headers, self.origin)
        cookie_values = [value for key, value in headers.items() if key.lower() == "cookie"]
        if len(cookie_values) != 1 or len(cookie_values[0]) > 4096:
            raise SomaError("UNAUTHENTICATED", "browser authentication failed")
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_values[0])
            token = cookie[COOKIE_NAME].value
            if not token.isascii() or len(token) != 43:
                raise ValueError
            key = hashlib.sha256(token.encode("ascii")).digest()
        except (CookieError, KeyError, ValueError):
            raise SomaError("UNAUTHENTICATED", "browser authentication failed") from None
        with self._lock:
            now = self.monotonic()
            self._expire(now)
            value = self._sessions.get(key)
            if value is None:
                raise SomaError("UNAUTHENTICATED", "browser authentication failed")
            session, _, absolute = value
            if mutation:
                origins = [value for name, value in headers.items() if name.lower() == "origin"]
                csrf = [value for name, value in headers.items() if name.lower() == "x-soma-csrf"]
                site = headers.get("sec-fetch-site")
                if origins != [self.origin] or len(csrf) != 1 or not csrf[0].isascii() or not hmac.compare_digest(csrf[0], session.csrf_token) or site is not None and site not in {"same-origin", "none"}:
                    raise SomaError("FORBIDDEN", "browser mutation context is invalid")
            self._sessions[key] = (session, now, absolute)
            fingerprint = hashlib.sha256(b"SOMA-BROWSER-SESSION-V1\0" + key).hexdigest()
            return AuthenticatedBrowserContextV1(session.actor_id, session.run_id, fingerprint, self.origin)

    def invalidate_all(self, reason):
        with self._lock:
            self._sessions.clear()
