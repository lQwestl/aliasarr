#!/usr/bin/env python3
"""Run the unittest suite and reject silently skipped tests in CI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}
BLOCKED_REQUESTS: list[str] = []


def block_external_network() -> None:
    """Тесты не должны ходить в интернет.

    Несколько тестов обновления метаданных незаметно скачивали постеры с TMDB и
    TheTVDB: в CI это делало результат зависимым от доступности чужих сервисов,
    а без сети те же тесты шли по другой ветке кода. Внешние запросы через httpx
    и urllib теперь сразу получают ошибку соединения; подменённые транспорты
    (MockTransport, ASGITransport) работают как обычно.
    """
    import urllib.request

    import httpx

    def _blocked(host: str, transport) -> bool:
        if host in _LOCAL_HOSTS:
            return False
        return not isinstance(transport, (httpx.MockTransport, httpx.ASGITransport))

    original_async_send = httpx.AsyncClient.send
    original_send = httpx.Client.send

    async def async_send(self, request, *args, **kwargs):
        if _blocked(request.url.host, self._transport):
            BLOCKED_REQUESTS.append(str(request.url))
            raise httpx.ConnectError("External network access is disabled in tests", request=request)
        return await original_async_send(self, request, *args, **kwargs)

    def send(self, request, *args, **kwargs):
        if _blocked(request.url.host, self._transport):
            BLOCKED_REQUESTS.append(str(request.url))
            raise httpx.ConnectError("External network access is disabled in tests", request=request)
        return original_send(self, request, *args, **kwargs)

    def urlopen(url, *args, **kwargs):
        BLOCKED_REQUESTS.append(str(getattr(url, "full_url", url)))
        raise OSError("External network access is disabled in tests")

    httpx.AsyncClient.send = async_send
    httpx.Client.send = send
    urllib.request.urlopen = urlopen


def main() -> int:
    block_external_network()
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if result.skipped:
        print("\nUnexpected skipped tests:", file=sys.stderr)
        for test, reason in result.skipped:
            print(f"- {test}: {reason}", file=sys.stderr)

    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
