"""First-run setup and password login; reset/change/auto-login are uncomposed."""
import hashlib
import hmac
import secrets
from threading import Lock

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, SecurityNotReady, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import ObjectContract
from soma.reference.application.profile_service import LocalUserProfileService
from soma.security.auth.passwords import AuthenticationThrottle, PasswordVerifierProvider
from soma.security.runtime.control import publish_owned_file, read_owned_file


class AuthenticationService:
    def __init__(self, factory, security):
        self.factory, self.security = factory, security
        self.passwords = PasswordVerifierProvider()
        self.throttle = AuthenticationThrottle()
        self.profiles = LocalUserProfileService(factory)
        self.setup_lock = Lock()
        registry = AuditRegistry()
        fields = frozenset({"verifier_profile"})
        registry.register(AuditActionContract(action_type="security.local_admin_configured", action_version=1,
            payload_schema="SecurityLocalAdminConfiguredAuditV1", payload_version=1,
            payload_contract=ObjectContract(name="SecurityLocalAdminConfiguredAuditV1", version=1,
                required_fields=fields, allowed_fields=fields, max_utf8_bytes=1024)))
        self.boundary = CommandBoundary(factory, AuditWriter(registry))

    def _credential(self):
        with ReadSnapshot(self.factory) as snapshot:
            return snapshot.connection.execute("SELECT c.local_user_profile_id,c.verifier_phc,c.security_revision,p.display_name,c.reset_verifier_sha256 "
                "FROM security_auth_credentials c JOIN local_user_profiles p USING(local_user_profile_id) WHERE c.singleton_guard=1").fetchone()

    def status(self, request):
        row = self._credential()
        authenticated = False
        try:
            context = self.security.validate_request(request, mutation=False)
            authenticated = row is not None and context.actor_id == row[0]
        except SomaError:
            pass
        return {"configured": row is not None, "authenticated": authenticated,
            "auto_login_enabled": False, "security_revision": None if row is None else row[2],
            "display_name": None if row is None else row[3]}

    def _session(self, profile_id, display_name):
        session = self.security.sessions.issue_session(self.security.control._run_id, profile_id)
        return {"authenticated": True, "actor_id": profile_id, "display_name": display_name,
            "csrf_token": session.csrf_token, "session_expires_at_utc": session.absolute_expires_at_utc}, session.cookie

    def login(self, body):
        if not isinstance(body, dict) or set(body) != {"password"}:
            raise ValidationError("login fields are invalid")
        self.throttle.check()
        row = self._credential()
        if row is None:
            raise SomaError("AUTH_NOT_CONFIGURED", "first-run setup is required")
        valid = self.passwords.verify(row[1], body["password"])
        self.throttle.record(valid)
        if not valid:
            raise SomaError("AUTH_INVALID_CREDENTIALS", "authentication failed")
        return self._session(row[0], row[3])

    def setup(self, body):
        if not isinstance(body, dict) or set(body) != {"command_id", "password", "password_confirmation"}:
            raise ValidationError("setup fields are invalid")
        command_id = require_uuid4(body["command_id"])
        # Expensive preparation and protected-file I/O stay outside the writer UoW.
        verifier = self.passwords.hash(body["password"], body["password_confirmation"])
        semantic_hash = hashlib.sha256(b"SOMA-SETUP-PASSWORD-V1\0" + self.passwords.password_bytes(body["password"])).hexdigest()
        envelope = CommandEnvelope(command_id, "SetupLocalAdmin", "security_configuration", self.security.installation_id,
            {"password_sha256": semantic_hash, "confirmation_sha256": semantic_hash})
        with self.setup_lock:
            path = self.security.root / "security" / "admin-reset.dpapi"
            protected = None
            reset_digest = None
            if self._credential() is None:
                if not self.security.ownership():
                    raise SecurityNotReady("setup requires canonical host ownership")
                if path.exists():
                    # An orphan is non-authoritative; validate ownership before replacement.
                    orphan = read_owned_file(path, self.security.file_security)
                    if not self.security.file_security.remove_exact_file(path, orphan):
                        raise SecurityNotReady("administrator reset orphan changed during reconciliation")
                reset_secret = secrets.token_bytes(32)
                reset_digest = hashlib.sha256(reset_secret).digest()
                protected = self.security.dpapi.protect_current_user(reset_secret, "admin_password_reset", self.security.installation_id)
                publish_owned_file(path, protected, self.security.file_security)
                if not hmac.compare_digest(reset_secret, self.security.dpapi.unprotect_current_user(
                    read_owned_file(path, self.security.file_security), "admin_password_reset", self.security.installation_id)):
                    raise SecurityNotReady("administrator reset envelope did not verify")
                del reset_secret

            def prepare(uow):
                if uow.connection.execute("SELECT 1 FROM security_auth_credentials WHERE singleton_guard=1").fetchone() is not None:
                    raise SomaError("AUTH_ALREADY_CONFIGURED", "administrator is already configured")
                existing = uow.connection.execute("SELECT local_user_profile_id,display_name FROM local_user_profiles WHERE singleton_guard=1").fetchone()
                profile_id = new_uuid4() if existing is None else existing[0]
                display_name = "Local Administrator" if existing is None else existing[1]
                now = utc_epoch_seconds()

                def apply(inner):
                    if existing is None:
                        self.profiles.ensure_singleton_local_administrator(inner, parent_command_id=command_id, profile_id=profile_id)
                    inner.connection.execute("INSERT INTO security_auth_credentials VALUES(1,? ,?,'ARGON2ID_V1',1,?,?,?)",
                        (profile_id, verifier, now, now, reset_digest))
                    return AuditEventInput(audit_event_id=new_uuid4(), action_type="security.local_admin_configured", action_version=1,
                        actor_kind="local_user", actor_id=profile_id, target_type="local_user_profile", target_id=profile_id,
                        command_id=command_id, payload_schema="SecurityLocalAdminConfiguredAuditV1", payload_version=1,
                        payload={"verifier_profile": "ARGON2ID_V1"}, resulting_event_refs=(AuditResultRef("local_user_profile", profile_id),))

                # Only immutable non-secret setup evidence enters the receipt.
                return PreparedMutation(no_change=False, result_type="local_user_profile", result_id=profile_id, apply=apply,
                    response_schema="LocalAdminConfiguredV1", response_version=1,
                    response={"actor_id": profile_id, "display_name": display_name, "security_revision": 1})

            try:
                result = self.boundary.execute(envelope, prepare)
            except BaseException:
                if protected is not None:
                    try:
                        committed = self._credential()
                        if (committed is None or committed[4] != reset_digest) and read_owned_file(path, self.security.file_security) == protected:
                            self.security.file_security.remove_exact_file(path, protected)
                    except (OSError, SomaError):
                        pass  # Exact-owned orphan cleanup is best-effort, never authority.
                raise
            return self._session(result.response["actor_id"], result.response["display_name"])
