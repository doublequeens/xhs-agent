from .deepseek_model import DeepSeekModel
from .gemini_model import GeminiModel
from .zhipu_model import ZhipuModel
from .base import BaseLLMModel

__all__ = [
    "DeepSeekModel",
    "GeminiModel",
    "ZhipuModel",
    "BaseLLMModel"
]

_model_cache = {}

def get_model(provider: str, tools: list = None, **kwargs):
    """
    Factory function to get the appropriate model instance based on model_type.

    Args:
        provider (str): The provider of the model to instantiate. Options are 'deepseek', 'gemini', 'zhipu'.
        **kwargs: Additional keyword arguments to pass to the model constructor.

    Returns:
        An instance of the requested model.
    """
    provider = provider.lower()
    
    # Create a unique cache key based on provider, tools, and kwargs
    tool_names = tuple(getattr(t, "name", str(t)) for t in tools) if tools else ()
    kwarg_items = tuple(sorted(kwargs.items()))
    cache_key = (provider, tool_names, kwarg_items)
    
    if cache_key not in _model_cache:
        if provider == "deepseek":
            _model_cache[cache_key] = DeepSeekModel(tools=tools, **kwargs)
        elif provider == "gemini":
            _model_cache[cache_key] = GeminiModel(tools=tools, **kwargs)
        elif provider == "glm":
            _model_cache[cache_key] = ZhipuModel(tools=tools, **kwargs)
        else:
            raise ValueError(f"Unsupported model provider: {provider}")
            
    return _model_cache[cache_key]