from __future__ import annotations

import asyncio
import threading
import urllib.request

import pytest

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from soma.foundation.errors import SomaError
from soma.foundation.runtime import BoundLoopbackSocket, UvicornLoopbackServer


async def _hello(request):
    return PlainTextResponse("ok")


def test_uvicorn_adapter_serves_on_prebound_loopback_socket() -> None:
    app = Starlette(routes=[Route("/", _hello, methods=["GET"])])
    adapter = UvicornLoopbackServer(
        app,
        self_health_probe=lambda expected: True,
        startup_timeout_seconds=10,
        shutdown_timeout_seconds=10,
    )
    with BoundLoopbackSocket.bind() as bound:
        adapter.start(bound.socket)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{bound.port}/",
                timeout=5,
            ) as response:
                assert response.status == 200
                assert response.read() == b"ok"
        finally:
            adapter.stop()



def test_uvicorn_start_failure_is_reported_stopped_and_cleanup_can_observe_it(
    monkeypatch,
) -> None:
    app = Starlette(routes=[Route("/", _hello, methods=["GET"])])
    adapter = UvicornLoopbackServer(
        app,
        self_health_probe=lambda expected: True,
        startup_timeout_seconds=1,
        shutdown_timeout_seconds=1,
    )

    async def fail_serve(*, sockets) -> None:
        raise RuntimeError("injected uvicorn serve failure")

    monkeypatch.setattr(adapter._server, "serve", fail_serve)
    with BoundLoopbackSocket.bind() as bound:
        with pytest.raises(SomaError, match="Uvicorn failed during startup"):
            adapter.start(bound.socket)

        assert adapter.is_stopped()
        with pytest.raises(SomaError, match="Uvicorn server failed"):
            adapter.stop(timeout_seconds=0)
        assert adapter.is_stopped()


def test_uvicorn_stop_respects_zero_remaining_budget_and_can_retry(
    monkeypatch,
) -> None:
    app = Starlette(routes=[Route("/", _hello, methods=["GET"])])
    adapter = UvicornLoopbackServer(
        app,
        self_health_probe=lambda expected: True,
        startup_timeout_seconds=0.03,
        shutdown_timeout_seconds=1,
    )
    release = threading.Event()

    async def blocked_serve(*, sockets) -> None:
        while not release.is_set():
            await asyncio.sleep(0.005)

    monkeypatch.setattr(adapter._server, "serve", blocked_serve)
    with BoundLoopbackSocket.bind() as bound:
        with pytest.raises(
            SomaError,
            match="Uvicorn did not become ready before startup deadline",
        ):
            adapter.start(bound.socket)

        assert not adapter.is_stopped()
        with pytest.raises(
            SomaError,
            match="Uvicorn did not stop before shutdown deadline",
        ):
            adapter.stop(timeout_seconds=0)
        assert not adapter.is_stopped()

        release.set()
        adapter.stop(timeout_seconds=1)
        assert adapter.is_stopped()
