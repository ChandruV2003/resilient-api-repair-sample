from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
import csv
import json
import os
import tempfile
import time


RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str
    headers: Mapping[str, str]


class Transport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse: ...


class ApiProtocolError(RuntimeError):
    """The service returned a response that violates the expected contract."""


class RetryExhaustedError(RuntimeError):
    """A retryable request still failed after the configured attempt limit."""


class ResilientApiClient:
    def __init__(
        self,
        transport: Transport,
        *,
        max_attempts: int = 3,
        max_pages: int = 100,
        timeout_seconds: float = 10.0,
        max_delay_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if timeout_seconds <= 0 or max_delay_seconds < 0:
            raise ValueError("timeouts must be positive and delays non-negative")
        self._transport = transport
        self._max_attempts = max_attempts
        self._max_pages = max_pages
        self._timeout_seconds = timeout_seconds
        self._max_delay_seconds = max_delay_seconds
        self._sleep = sleep

    def fetch_all(self, url: str) -> list[dict[str, Any]]:
        if not url.startswith(("https://", "http://")):
            raise ValueError("url must use http or https")

        records: list[dict[str, Any]] = []
        cursor = ""
        seen_cursors: set[str] = set()

        for _ in range(self._max_pages):
            response = self._request_page(url, cursor)
            page, next_cursor = _decode_page(response.body)
            records.extend(page)

            if next_cursor is None:
                return records
            if next_cursor in seen_cursors:
                raise ApiProtocolError(f"pagination cursor repeated: {next_cursor!r}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise ApiProtocolError(f"pagination exceeded {self._max_pages} pages")

    def _request_page(self, url: str, cursor: str) -> HttpResponse:
        params = {"cursor": cursor} if cursor else {}
        for attempt in range(1, self._max_attempts + 1):
            response = self._transport.get(
                url,
                params=params,
                timeout_seconds=self._timeout_seconds,
            )
            if response.status == 200:
                return response
            if response.status not in RETRYABLE_STATUSES:
                raise ApiProtocolError(f"unexpected HTTP status {response.status}")
            if attempt == self._max_attempts:
                raise RetryExhaustedError(
                    f"HTTP {response.status} after {self._max_attempts} attempts"
                )
            self._sleep(self._retry_delay(response.headers, attempt))

        raise AssertionError("attempt loop ended unexpectedly")

    def _retry_delay(self, headers: Mapping[str, str], attempt: int) -> float:
        raw = next(
            (value for key, value in headers.items() if key.lower() == "retry-after"),
            "",
        )
        try:
            delay = float(raw)
        except ValueError:
            delay = float(2 ** (attempt - 1))
        return max(0.0, min(delay, self._max_delay_seconds))


def _decode_page(body: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiProtocolError("response body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ApiProtocolError("response must be a JSON object")

    data = payload.get("data")
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ApiProtocolError("response data must be a list of objects")

    next_cursor = payload.get("next_cursor")
    if next_cursor in {None, ""}:
        return list(data), None
    if not isinstance(next_cursor, str) or len(next_cursor) > 500:
        raise ApiProtocolError("next_cursor must be a bounded string or null")
    return list(data), next_cursor


def write_csv_atomic(
    rows: Sequence[Mapping[str, Any]],
    destination: Path,
    columns: Sequence[str],
) -> None:
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("columns must be a non-empty unique sequence")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
