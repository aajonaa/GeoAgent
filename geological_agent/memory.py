from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    text: str
    source_run_id: str


class MemoryStore(Protocol):
    def search(self, query: str, *, limit: int) -> Sequence[MemoryRecord]: ...
    def write(self, record: MemoryRecord) -> None: ...


class NullMemoryStore:
    """Explicitly disabled memory: writes are not persisted."""

    def search(self, query, *, limit=5):
        return ()

    def write(self, record):
        return None
