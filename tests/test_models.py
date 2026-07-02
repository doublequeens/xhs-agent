from unittest.mock import MagicMock

import pytest
from unittest.mock import patch
from src.models import get_model, _model_cache

@pytest.fixture(autouse=True)
def clear_cache():
    _model_cache.clear()
    yield
    _model_cache.clear()

def test_get_model_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported model provider: unknown"):
        get_model("unknown")

@patch("src.models.DeepSeekModel")
@patch("src.models.GeminiModel")
@patch("src.models.ZhipuModel")
def test_get_model_supported_providers(mock_zhipu, mock_gemini, mock_deepseek):
    # Test deepseek
    get_model("deepseek")
    mock_deepseek.assert_called_once()

    # Test gemini
    get_model("gemini")
    mock_gemini.assert_called_once()

    # Test glm (which uses ZhipuModel)
    get_model("glm")
    mock_zhipu.assert_called_once()

@patch("src.models.DeepSeekModel")
def test_get_model_caching(mock_deepseek):
    # First call
    model1 = get_model("deepseek")
    # Second call with same arguments
    model2 = get_model("deepseek")

    assert model1 is model2
    assert mock_deepseek.call_count == 1

@patch("src.models.DeepSeekModel")
def test_get_model_with_tools_and_kwargs(mock_deepseek):
    tools = [MagicMock(name="tool1")]
    tools[0].name = "tool1"

    get_model("deepseek", tools=tools, temperature=0.5)

    mock_deepseek.assert_called_once_with(tools=tools, temperature=0.5)
