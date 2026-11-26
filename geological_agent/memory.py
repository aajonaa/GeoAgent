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


class SnapshotMemoryStore:
    """A bounded broker-provided snapshot. Workers receive no memory credentials."""

    def __init__(self, records=()):
        records = tuple(records)
        if len(records) > 3:
            raise ValueError("At most three memory references are allowed")
        for record in records:
            if (not isinstance(record, MemoryRecord) or not isinstance(record.id, str)
                    or not 1 <= len(record.id) <= 256 or not isinstance(record.text, str)
                    or not 1 <= len(record.text) <= 4000
                    or record.source_run_id != "external-memory-unverified"):
                raise ValueError("Invalid untrusted memory snapshot")
        self.records = records

    @classmethod
    def from_payload(cls, rows):
        if not isinstance(rows, (list, tuple)) or len(rows) > 3:
            raise ValueError("Invalid memory snapshot")
        if any(not isinstance(row, dict) or set(row) != {"id", "text", "source_run_id"} for row in rows):
            raise ValueError("Invalid memory snapshot fields")
        return cls(MemoryRecord(**row) for row in rows)

    def search(self, query, *, limit=3):
        return self.records[:max(0, min(limit, 3))]

    def write(self, record):
        raise PermissionError("Automatic memory writes are disabled; explicit account approval is required")
