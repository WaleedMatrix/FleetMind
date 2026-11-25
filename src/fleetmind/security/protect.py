"""Default-deny ASGI authorization, request bounds, and streaming session checks."""

from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from fleetmind.security.settings import SecuritySettings
from fleetmind.security.store import SecurityStore, now, valid_csrf

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOGIN = "/api/v1/auth/login"
PREDICT = "/api/v1/predict"
AUTH = "/api/v1/auth/"
COPILOT = "/api/v1/copilot"
CHAT = COPILOT + "/chat"
STREAM = "/api/v1/telemetry/stream"


@dataclass(frozen=True)
class Policy:
    role: str = "viewer"
    bucket: str | None = None
    per_minute: int = 0
    stream: str | None = None
    size: int = 65_536


def permissions(method, path):
    if path.startswith("/api/v1/admin/"):
        return (
            Policy("administrator", "admin_write", 30)
            if method not in SAFE_METHODS
            else Policy("administrator")
        )
    if path.startswith(AUTH):
        return (
            Policy(bucket="password", per_minute=5, size=4096)
            if path == AUTH + "password"
            else Policy()
        )
    if path.startswith(COPILOT + "/"):
        if path.endswith("/messages/stream"):
            return Policy("engineer", "copilot", 12, "copilot", 8192)
        if path == CHAT:
            return Policy("engineer", "copilot", 12, size=8192)
        return (
            Policy("engineer", "copilot_write", 45)
            if method not in SAFE_METHODS
            else Policy("engineer")
        )
    if path.startswith("/api/v1/knowledge/"):
        return (
            Policy("engineer", "knowledge", 30, size=8192)
            if method == "POST"
            else Policy("engineer")
        )
    if path == STREAM:
        return Policy(stream="telemetry")
    if path == "/api/v1/telemetry/dead-letters":
        return Policy("engineer")
    if path == PREDICT:
        return Policy("engineer", "prediction", 60, size=8192)
    if path.endswith("/explanation"):
        return Policy(bucket="explanation", per_minute=30)
    return Policy("engineer" if method not in SAFE_METHODS else "viewer")


def allowed(role, required):
    return (
        role == "administrator"
        or role == required
        or (role == "engineer" and required == "viewer")
    )


class Limits:
    """Bounded, process-local rolling minute counters and request leases."""

    def __init__(self):
        self.lock = Lock()
        self.history = OrderedDict()
        self.leases = {}

    def take(self, key, count):
        t = monotonic()
        with self.lock:
            # Expire idle keys before admitting new ones.
            while self.history and next(iter(self.history.values()))[-1] <= t - 60:
                self.history.popitem(last=False)
            if key not in self.history:
                if len(self.history) >= 8192:
                    return 60
                self.history[key] = deque()
            trail = self.history[key]
            while trail and trail[0] <= t - 60:
                trail.popleft()
            if len(trail) >= count:
                return max(1, int(trail[0] + 61 - t))
            trail.append(t)
            self.history.move_to_end(key)
            return None

    def enter(self, name, principal_id, per_principal, global_limit):
        with self.lock:
            key = (name, principal_id)
            global_key = (name, None)
            if (
                self.leases.get(key, 0) >= per_principal
                or self.leases.get(global_key, 0) >= global_limit
            ):
                return False
            for item in (key, global_key):
                self.leases[item] = self.leases.get(item, 0) + 1
            return True

    def leave(self, name, principal_id):
        with self.lock:
            for item in ((name, principal_id), (name, None)):
                self.leases[item] -= 1
                if self.leases[item] == 0:
                    self.leases.pop(item)


def security_settings(request):
    return (
        getattr(request.app.state, "security_settings", None)
        or SecuritySettings.from_environment()
    )


def security_store(request):
    return getattr(request.app.state, "security_store", None) or SecurityStore()


class StreamSession:
    """Periodic database verification without keeping a session open."""

    def __init__(self, store, principal, token, required):
        self.store, self.principal, self.token, self.required = (
            store,
            principal,
            token,
            required,
        )
        self.last = monotonic()

    async def check(self, *, force=False):
        if self.principal.expires_at <= now():
            return False
        if not force and monotonic() - self.last < 3:
            return True
        try:
            current = await run_in_threadpool(self.store.authenticate, self.token)
        except SQLAlchemyError:
            return False
        self.last = monotonic()
        return (
            current is not None
            and current.id == self.principal.id
            and current.session_id == self.principal.session_id
            and allowed(current.role, self.required)
        )


async def stream_allowed(request, *, force=False):
    guard = getattr(getattr(request, "state", None), "stream_session", None)
    return guard is None or await guard.check(force=force)


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.limits = Limits()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        method, path = request.method, scope["path"]
        if path == "/health" and method == "GET":
            await self.app(scope, receive, self.response_headers(send, secure=False))
            return
        try:
            settings = security_settings(request)
        except (ValueError, TypeError):
            await self.error(
                scope, receive, send, 503, "Security configuration is unavailable."
            )
            return
        secure_send = self.response_headers(
            send, secure=not settings.insecure_local_http
        )
        store = security_store(request)
        limits = getattr(request.app.state, "security_limits", self.limits)
        peer = request.client.host if request.client else "unknown"
        request.state.auth_settings = settings
        request.state.auth_store = store
        request.state.auth_limits = limits

        async def fail(status, detail, retry=None):
            await self.error(scope, receive, secure_send, status, detail, retry)

        async def audit_denial(principal=None):
            if not limits.take(("denials", peer), 12):
                actor = principal.id if principal and not principal.is_service else None
                await run_in_threadpool(store.record, "authorization_denied", actor)

        login = path == LOGIN and method == "POST"
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.origins:
            await audit_denial()
            await fail(403, "Request origin is not trusted.")
            return
        policy = permissions(method, path)
        principal = None
        lease = None
        if login:
            if origin is None:
                await audit_denial()
                await fail(403, "A trusted origin is required.")
                return
            retry = limits.take(("login_peer", peer), 40)
            if retry:
                await fail(429, "Too many sign-in attempts. Retry shortly.", retry)
                return
            policy = Policy(size=4096)
        else:
            auth_header = request.headers.get("authorization")
            is_service = auth_header is not None
            if is_service:
                scheme, _, credential = auth_header.partition(" ")
                token = credential if scheme.lower() == "bearer" else None
            else:
                token = request.cookies.get(settings.cookie)
            try:
                principal = await run_in_threadpool(
                    lambda: store.authenticate(token, service=is_service)
                )
            except SQLAlchemyError:
                await fail(503, "Authentication storage is unavailable.")
                return
            if principal is None:
                await audit_denial()
                await fail(401, "Sign in to continue.")
                return
            permitted = (
                method == "POST" and path == PREDICT
                if is_service
                else allowed(principal.role, policy.role)
            )
            if not permitted:
                await audit_denial(principal)
                await fail(403, "You do not have access to this operation.")
                return
            if (
                not is_service
                and method not in SAFE_METHODS
                and (
                    origin is None
                    or not valid_csrf(token, request.headers.get("x-fleetmind-csrf"))
                )
            ):
                await audit_denial(principal)
                await fail(403, "Request verification failed.")
                return
            if policy.bucket and (
                retry := limits.take((policy.bucket, principal.id), policy.per_minute)
            ):
                await fail(429, "Request limit reached. Retry shortly.", retry)
                return
            request.state.principal = principal
            if policy.stream or policy.bucket == "copilot":
                lease = policy.stream or "copilot"
                per_user, total = (3, 32) if lease == "telemetry" else (1, 8)
                if not limits.enter(lease, principal.id, per_user, total):
                    await fail(429, "Concurrent request limit reached.", 5)
                    return
                if policy.stream:
                    request.state.stream_session = StreamSession(
                        store, principal, token, policy.role
                    )

        async def examined_send(message):
            if (
                message["type"] == "http.response.start"
                and message["status"] == 404
                and path.startswith(COPILOT + "/conversations/")
                and principal
            ):
                await audit_denial(principal)
            await secure_send(message)

        try:
            if method not in SAFE_METHODS:
                length = request.headers.get("content-length")
                if length is not None and (
                    not length.isascii()
                    or not length.isdigit()
                    or len(length) > 10
                    or int(length) > policy.size
                ):
                    await fail(413, "Request body is too large.")
                    return
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > policy.size:
                        await fail(413, "Request body is too large.")
                        return
                    body.extend(chunk)
                    if not message.get("more_body"):
                        break
                sent = False

                async def bounded_receive():
                    nonlocal sent
                    if sent:
                        return await receive()
                    sent = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }

                await self.app(scope, bounded_receive, examined_send)
            else:
                await self.app(scope, receive, examined_send)
        finally:
            if lease is not None:
                limits.leave(lease, principal.id)

    @staticmethod
    def response_headers(send, *, secure):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                if secure:
                    message["headers"].append(
                        (b"strict-transport-security", b"max-age=31536000")
                    )
            await send(message)

        return wrapped

    @staticmethod
    async def error(scope, receive, send, status, detail, retry=None):
        headers = {"Retry-After": str(retry)} if retry else {}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        await JSONResponse({"detail": detail}, status_code=status, headers=headers)(
            scope, receive, send
        )
