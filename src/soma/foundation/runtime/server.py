from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable

import uvicorn

from soma.foundation.contracts.foundation import RuntimeHealth
from soma.foundation.errors import SomaError

SelfHealthProbe = Callable[[RuntimeHealth], bool]


class UvicornLoopbackServer:
    """Concrete one-worker ASGI adapter consuming HostRuntime's pre-bound socket."""

    def __init__(
        self,
        app: Any,
        *,
        self_health_probe: SelfHealthProbe,
        startup_timeout_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 10.0,
    ) -> None:
        if startup_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise ValueError("server lifecycle timeouts must be positive")
        self._probe = self_health_probe
        self._startup_timeout = startup_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._server = uvicorn.Server(
            uvicorn.Config(
                app=app,
                workers=1,
                proxy_headers=False,
                server_header=False,
                access_log=False,
                reload=False,
                lifespan="on",
                http="h11",
                ws="none",
                log_level="warning",
            )
        )
        self._thread: threading.Thread | None = None
        self._failure: BaseException | None = None

    def _serve(self, bound_socket) -> None:
        try:
            asyncio.run(self._server.serve(sockets=[bound_socket]))
        except BaseException as exc:
            self._failure = exc

    def start(self, bound_socket) -> None:
        if self._thread is not None:
            raise SomaError("INTERNAL_ERROR", "Uvicorn server adapter is already started")
        self._thread = threading.Thread(
            target=self._serve,
            args=(bound_socket,),
            name="soma-asgi",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if self._failure is not None:
                raise SomaError("INTERNAL_ERROR", "Uvicorn failed during startup") from self._failure
            if self._server.started:
                return
            if not self._thread.is_alive():
                raise SomaError("INTERNAL_ERROR", "Uvicorn stopped before becoming ready")
            time.sleep(0.01)
        self._server.should_exit = True
        raise SomaError("INTERNAL_ERROR", "Uvicorn did not become ready before startup deadline")

    def authenticated_self_health(self, expected: RuntimeHealth) -> bool:
        try:
            return bool(self._probe(expected))
        except BaseException:
            return False

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._server.should_exit = True
        thread.join(self._shutdown_timeout)
        if thread.is_alive():
            self._server.force_exit = True
            thread.join(self._shutdown_timeout)
        if thread.is_alive():
            raise SomaError("INTERNAL_ERROR", "Uvicorn did not stop before shutdown deadline")
        self._thread = None
        if self._failure is not None:
            failure = self._failure
            self._failure = None
            raise SomaError("INTERNAL_ERROR", "Uvicorn server failed") from failure
