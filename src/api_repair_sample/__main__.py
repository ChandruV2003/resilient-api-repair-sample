from __future__ import annotations

from collections import deque
from typing import Mapping
import json

from .client import HttpResponse, ResilientApiClient


class DemoTransport:
    def __init__(self) -> None:
        self.calls = 0
        self._responses = deque(
            [
                HttpResponse(503, "temporarily unavailable", {"Retry-After": "0"}),
                HttpResponse(
                    200,
                    json.dumps(
                        {"data": [{"id": 101}, {"id": 102}], "next_cursor": "p2"}
                    ),
                    {},
                ),
                HttpResponse(
                    200,
                    json.dumps({"data": [{"id": 103}], "next_cursor": None}),
                    {},
                ),
            ]
        )

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        del url, params, timeout_seconds
        self.calls += 1
        return self._responses.popleft()


def main() -> None:
    transport = DemoTransport()
    records = ResilientApiClient(transport, sleep=lambda _: None).fetch_all(
        "https://api.example.test/items"
    )
    print(f"Fetched {len(records)} records after {transport.calls} HTTP calls.")
    print("IDs:", ", ".join(str(item["id"]) for item in records))


if __name__ == "__main__":
    main()
