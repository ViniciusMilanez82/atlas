"""FAKE in-memory Vault backend for tests. Holds synthetic secrets only."""

from __future__ import annotations


class FakeInMemoryVaultBackend:
    name = "fake-in-memory"

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, locator: str, secret: bytes) -> None:
        self._data[locator] = secret

    def get(self, locator: str) -> bytes | None:
        return self._data.get(locator)

    def delete(self, locator: str) -> None:
        self._data.pop(locator, None)

    def __len__(self) -> int:
        return len(self._data)
