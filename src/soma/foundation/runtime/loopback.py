from __future__ import annotations

import socket

from soma.foundation.errors import SomaError


class BoundLoopbackSocket:
    """Already-bound exclusive loopback socket handed to the server adapter."""

    def __init__(self, value: socket.socket) -> None:
        self._socket: socket.socket | None = value

    @classmethod
    def bind(cls) -> "BoundLoopbackSocket":
        value = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                value.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            value.bind(("127.0.0.1", 0))
            host, port = value.getsockname()[:2]
            if host != "127.0.0.1" or type(port) is not int or port <= 0:
                raise OSError("unexpected loopback binding")
            return cls(value)
        except BaseException as exc:
            value.close()
            if isinstance(exc, SomaError):
                raise
            raise SomaError(
                "LOOPBACK_BIND_FAILED",
                "SOMA could not exclusively bind a loopback socket",
            ) from exc

    @property
    def socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("loopback socket is closed")
        return self._socket

    @property
    def port(self) -> int:
        return int(self.socket.getsockname()[1])

    @property
    def host(self) -> str:
        return str(self.socket.getsockname()[0])

    def close(self) -> None:
        if self._socket is not None:
            value = self._socket
            self._socket = None
            value.close()

    def __enter__(self) -> "BoundLoopbackSocket":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
