import os
from typing import Any, Mapping, Sequence


class TavilyEvidenceProvider:
    def __init__(self, *, api_key: str | None = None, client: Any | None = None):
        if client is not None:
            self._client = client
            return

        resolved_api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("TAVILY_API_KEY environment variable is required for TavilyEvidenceProvider")

        from tavily import TavilyClient

        self._client = TavilyClient(api_key=resolved_api_key)

    def search(self, query: str, domains: Sequence[str]) -> list[Mapping[str, Any]]:
        response = self._client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=False,
            include_raw_content=False,
            include_domains=list(domains),
        )
        results = response.get("results") if isinstance(response, Mapping) else None
        if not isinstance(results, list):
            raise RuntimeError("Tavily search response must contain a results list")
        return results
