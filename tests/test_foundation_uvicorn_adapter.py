from __future__ import annotations

import urllib.request

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

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
