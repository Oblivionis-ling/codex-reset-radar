from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx


class NetworkDisabledError(RuntimeError):
    pass


class NotificationTransportError(RuntimeError):
    pass


class HttpTransport:
    """One bounded retry owner for every HTTP notification adapter."""

    def __init__(
        self,
        *,
        network_enabled: bool = False,
        timeout_seconds: float = 10.0,
        retries: int = 1,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.network_enabled = network_enabled
        self.retries = max(0, min(2, retries))
        self.sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    async def request(self, method: str, url: str, **kwargs: object) -> tuple[httpx.Response, int]:
        if not self.network_enabled:
            raise NetworkDisabledError("notification network access is disabled")
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                response = await self.client.request(method, url, **kwargs)
                if response.status_code not in {408, 409, 429} and response.status_code < 500:
                    return response, attempt
                if attempt > self.retries:
                    return response, attempt
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                if attempt > self.retries:
                    raise NotificationTransportError(
                        f"notification transport failed: {type(error).__name__}"
                    ) from error
            await self.sleep(min(0.2 * attempt, 0.5))
        assert last_error is not None
        raise NotificationTransportError(
            f"notification transport failed: {type(last_error).__name__}"
        ) from last_error

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "HttpTransport":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
