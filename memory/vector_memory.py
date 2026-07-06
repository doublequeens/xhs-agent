from __future__ import annotations

import chromadb
from pathlib import Path
from typing import Any, Optional
from memory.embedding import embed_texts


class XHSVectorMemory:
    # _shared_conn = None
    def __init__(
        self,
        persist_dir: str | Path = "data/chroma",
        collection_name: str = "xhs_contents",
) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "XHS content semantic memory"},
        )

    def upsert_content(
        self,
        *,
        content_id: str,
        embedding_text: str,
        metadata: dict[str, Any],
    ) -> None:
        """
        将一篇内容写入/更新到向量库。
        metadata 只能放 Chroma 支持的简单类型：
        str/int/float/bool/None。
        list/dict 要转成 JSON string。
        """
        embedding = embed_texts([embedding_text])[0]

        safe_metadata = self._sanitize_metadata(metadata)

        self.collection.upsert(
            ids=[content_id],
            documents=[embedding_text],
            embeddings=[embedding],
            metadatas=[safe_metadata],
        )

    def query_similar(
        self,
        *,
        query_text: str,
        n_results: int = 5,
        where: Optional[dict[str, Any]] = None,
        domain: Optional[str] = None,
        subdomain: Optional[str] = None,
        allow_global: bool = False,
    ) -> list[dict[str, Any]]:
        embedding = embed_texts([query_text])[0]
        where_filter = self._build_where_filter(
            where=where,
            domain=domain,
            subdomain=subdomain,
            allow_global=allow_global,
        )

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        output: list[dict[str, Any]] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for content_id, doc, meta, distance in zip(ids, documents, metadatas, distances):
            output.append(
                {
                    "content_id": content_id,
                    "document": doc,
                    "metadata": meta,
                    "distance": distance,
                    "similarity": self._distance_to_similarity(distance),
                }
            )

        return output

    def delete_content_by_id(self, content_id: str) -> None:
        self.collection.delete(ids=[content_id])

    def count(self) -> int:
        return self.collection.count()

    def _distance_to_similarity(self, distance: float) -> float:
        """
        Chroma 默认距离值越小越相似。
        这里给一个便于业务判断的近似 similarity。
        如果你后面统一用 cosine，可再精细化。
        """
        return 1 / (1 + distance)

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for k, v in metadata.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                safe[k] = v
            else:
                safe[k] = str(v)
        return safe

    def _build_where_filter(
        self,
        *,
        where: Optional[dict[str, Any]],
        domain: Optional[str],
        subdomain: Optional[str],
        allow_global: bool,
    ) -> Optional[dict[str, Any]]:
        has_domain = domain is not None
        has_subdomain = subdomain is not None
        if not allow_global and (not has_domain or not has_subdomain):
            raise ValueError(
                "query_similar requires both domain and subdomain unless allow_global=True"
            )
        if has_domain != has_subdomain:
            raise ValueError("query_similar requires domain and subdomain together")

        clauses: list[dict[str, Any]] = []
        if where:
            clauses.append(where)
        if has_domain:
            clauses.append({"domain": {"$eq": domain}})
        if has_subdomain:
            clauses.append({"subdomain": {"$eq": subdomain}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
