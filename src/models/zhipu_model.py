from langchain_community.chat_models import ChatZhipuAI
from .base import BaseLLMModel
import os, getpass

class ZhipuModel(BaseLLMModel):
    """
    A wrapper class for Zhipu AI models.
    """

    def __init__(self, model_name: str = "chatglm_pro", temperature: float = 0.7, **kwargs):
        """
        Initializes the ZhipuModel with the specified parameters.

        Args:
            model_name (str): The name of the Zhipu model to use.
            temperature (float): The temperature setting for the model.
        """
        self.temperature = temperature
        self.model_name = model_name
        self.api_key = os.getenv("ZHIPU_API_KEY")
        self.extra_kwargs = kwargs
        if not self.api_key:
            self.api_key = getpass.getpass("Please enter your Zhipu API Key: ")
            if not self.api_key:
                raise ValueError("Zhipu API Key is required.")

    def get_chat_model(self):
        """
        Creates and returns a ChatZhipuAI model instance.

        Returns:
            ChatZhipuAI: An instance of the chat model.
        """

        return ChatZhipuAI(
            model=self.model_name,
            api_key=self.api_key,
            temperature=self.temperature,
            **self.extra_kwargs
        )