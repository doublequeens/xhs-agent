from langchain_deepseek import ChatDeepSeek
from langchain_core.language_models import BaseChatModel
from src.models.base import BaseLLMModel
import os, getpass

class DeepSeekModel(BaseLLMModel):
    def __init__(self, model_name: str = "deepseek-reasoner", temperature: float = 0.3, **kwargs):
        self.model_name = model_name
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.temperature = temperature
        self.extra_kargs = kwargs
        if not self.api_key:
            self.api_key = getpass.getpass("Please enter your DeepSeek API Key: ")
            if not self.api_key:
                raise ValueError("DeepSeek API Key is required.")

    def get_chat_model(self, **kwargs):
        """
        Creates and returns a ChatDeepSeek model instance.

        Returns:
            ChatDeepSeek: An instance of the chat model.
        """

        return ChatDeepSeek(
            model=self.model_name,
            api_key=self.api_key,
            temperature=self.temperature,
            **self.extra_kargs
        )