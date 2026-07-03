from __future__ import annotations

from memory.vector_memory import XHSVectorMemory


class FakeCollection:
    def __init__(self):
        self.upsert_calls = []
        self.query_calls = []

    def upsert(self, **kwargs):
        self.upsert_calls.append(kwargs)

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {
            "ids": [["content-1"]],
            "documents": [["semantic doc"]],
            "metadatas": [[{"domain": "wellness", "subdomain": "sleep"}]],
            "distances": [[0.25]],
        }

    def delete(self, **kwargs):
        return None

    def count(self):
        return 1


class FakeClient:
    def __init__(self, collection: FakeCollection):
        self.collection = collection

    def get_or_create_collection(self, **_kwargs):
        return self.collection


def test_query_similar_adds_exact_domain_subdomain_where_filter(monkeypatch, tmp_path):
    collection = FakeCollection()

    monkeypatch.setattr("memory.vector_memory.chromadb.PersistentClient", lambda path: FakeClient(collection))
    monkeypatch.setattr("memory.vector_memory.embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])

    memory = XHSVectorMemory(persist_dir=tmp_path / "chroma")
    results = memory.query_similar(
        query_text="sleep routine",
        n_results=3,
        domain="wellness",
        subdomain="sleep",
    )

    assert collection.query_calls == [
        {
            "query_embeddings": [[0.1, 0.2, 0.3]],
            "n_results": 3,
            "where": {
                "$and": [
                    {"domain": {"$eq": "wellness"}},
                    {"subdomain": {"$eq": "sleep"}},
                ]
            },
            "include": ["documents", "metadatas", "distances"],
        }
    ]
    assert results[0]["metadata"] == {"domain": "wellness", "subdomain": "sleep"}


def test_upsert_content_sanitizes_and_preserves_domain_partition_metadata(monkeypatch, tmp_path):
    collection = FakeCollection()

    monkeypatch.setattr("memory.vector_memory.chromadb.PersistentClient", lambda path: FakeClient(collection))
    monkeypatch.setattr("memory.vector_memory.embed_texts", lambda texts: [[0.4, 0.5] for _ in texts])

    memory = XHSVectorMemory(persist_dir=tmp_path / "chroma")
    memory.upsert_content(
        content_id="content-1",
        embedding_text="sleep routine content",
        metadata={
            "domain": "wellness",
            "subdomain": "sleep",
            "content_intent": "how_to",
            "profile_version": "wellness-v1",
            "risk_level": "low",
            "strategy_tags": ["sleep", "routine"],
        },
    )

    assert collection.upsert_calls == [
        {
            "ids": ["content-1"],
            "documents": ["sleep routine content"],
            "embeddings": [[0.4, 0.5]],
            "metadatas": [
                {
                    "domain": "wellness",
                    "subdomain": "sleep",
                    "content_intent": "how_to",
                    "profile_version": "wellness-v1",
                    "risk_level": "low",
                    "strategy_tags": "['sleep', 'routine']",
                }
            ],
        }
    ]
