import pytest

from src.evidence import TavilyEvidenceProvider


def test_tavily_provider_requires_api_key_exact_message(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="^TAVILY_API_KEY environment variable is required for TavilyEvidenceProvider$",
    ):
        TavilyEvidenceProvider()


def test_tavily_provider_search_passes_expected_parameters():
    captured = {}

    class FakeClient:
        def search(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"results": [{"title": "Sleep", "url": "https://www.who.int/sleep", "content": "A"}]}

    provider = TavilyEvidenceProvider(client=FakeClient())
    results = provider.search("睡眠改善", ("who.int", "nih.gov"))

    assert results == [{"title": "Sleep", "url": "https://www.who.int/sleep", "content": "A"}]
    assert captured["kwargs"] == {
        "query": "睡眠改善",
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
        "include_domains": ["who.int", "nih.gov"],
    }


def test_tavily_provider_rejects_malformed_results_payload():
    class FakeClient:
        def search(self, **_kwargs):
            return {"results": "not-a-list"}

    provider = TavilyEvidenceProvider(client=FakeClient())

    with pytest.raises(RuntimeError, match="^Tavily search response must contain a results list$"):
        provider.search("睡眠改善", ("who.int",))
