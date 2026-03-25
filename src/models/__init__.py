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

def get_model(provider: str, **kwargs):
    """
    Factory function to get the appropriate model instance based on model_type.

    Args:
        provider (str): The provider of the model to instantiate. Options are 'deepseek', 'gemini', 'zhipu'.
        **kwargs: Additional keyword arguments to pass to the model constructor.

    Returns:
        An instance of the requested model.
    """
    provider = provider.lower()
    if provider == "deepseek":
        return DeepSeekModel(**kwargs)
    elif provider == "gemini":
        return GeminiModel(**kwargs)
    elif provider == "zhipu":
        return ZhipuModel(**kwargs)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")