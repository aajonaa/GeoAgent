from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    source: str


@dataclass(frozen=True)
class Evidence:
    text: str
    source_id: str
    provenance: str


class KnowledgeStore(Protocol):
    def get(self, source_id: str) -> Document | None: ...


class KnowledgeRetriever(Protocol):
    def search(self, query: str, *, limit: int) -> Sequence[Evidence]: ...


class NullKnowledgeStore:
    def get(self, source_id):
        return None


class NullKnowledgeRetriever:
    def search(self, query, *, limit=5):
        return ()
