from __future__ import annotations

from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping
import json
import unittest

from api_repair_sample import (
    ApiProtocolError,
    HttpResponse,
    ResilientApiClient,
    RetryExhaustedError,
    write_csv_atomic,
)


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls.append((url, dict(params), timeout_seconds))
        return self.responses.popleft()


def response(status: int, payload: object, **headers: str) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload), headers)


class ResilientApiClientTests(unittest.TestCase):
    def test_retries_transient_failure_and_paginates(self) -> None:
        transport = FakeTransport(
            [
                HttpResponse(503, "unavailable", {"Retry-After": "0.25"}),
                response(200, {"data": [{"id": 1}], "next_cursor": "page-2"}),
                response(200, {"data": [{"id": 2}], "next_cursor": None}),
            ]
        )
        delays: list[float] = []

        rows = ResilientApiClient(transport, sleep=delays.append).fetch_all(
            "https://api.example.test/items"
        )

        self.assertEqual(rows, [{"id": 1}, {"id": 2}])
        self.assertEqual(delays, [0.25])
        self.assertEqual(transport.calls[0][1], {})
        self.assertEqual(transport.calls[-1][1], {"cursor": "page-2"})

    def test_retry_after_is_capped_and_exhaustion_is_explicit(self) -> None:
        transport = FakeTransport(
            [
                HttpResponse(429, "busy", {"retry-after": "600"}),
                HttpResponse(429, "busy", {}),
            ]
        )
        delays: list[float] = []

        with self.assertRaisesRegex(RetryExhaustedError, "after 2 attempts"):
            ResilientApiClient(
                transport,
                max_attempts=2,
                max_delay_seconds=3,
                sleep=delays.append,
            ).fetch_all("https://api.example.test/items")

        self.assertEqual(delays, [3.0])

    def test_rejects_repeated_cursor(self) -> None:
        transport = FakeTransport(
            [
                response(200, {"data": [], "next_cursor": "same"}),
                response(200, {"data": [], "next_cursor": "same"}),
            ]
        )

        with self.assertRaisesRegex(ApiProtocolError, "cursor repeated"):
            ResilientApiClient(transport, sleep=lambda _: None).fetch_all(
                "https://api.example.test/items"
            )

    def test_rejects_malformed_record_collection(self) -> None:
        transport = FakeTransport(
            [response(200, {"data": ["not-an-object"], "next_cursor": None})]
        )

        with self.assertRaisesRegex(ApiProtocolError, "list of objects"):
            ResilientApiClient(transport).fetch_all(
                "https://api.example.test/items"
            )

    def test_atomic_csv_replaces_complete_destination(self) -> None:
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "nested" / "output.csv"
            destination.parent.mkdir()
            destination.write_text("old content\n", encoding="utf-8")

            write_csv_atomic(
                [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}],
                destination,
                ["id", "name"],
            )

            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "id,name\n1,Ada\n2,Grace\n",
            )
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])

    def test_atomic_csv_preserves_destination_when_generation_fails(self) -> None:
        class ExplodingRow(dict[str, object]):
            def get(self, key: str, default: object = None) -> object:
                del key, default
                raise RuntimeError("simulated serialization failure")

        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "output.csv"
            destination.write_text("known-good\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "serialization failure"):
                write_csv_atomic([ExplodingRow(id=1)], destination, ["id"])

            self.assertEqual(destination.read_text(encoding="utf-8"), "known-good\n")
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
