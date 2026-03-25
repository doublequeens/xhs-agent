import json
import os, getpass
from typing import List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from src.models.base import BaseLLMModel



class GeminiModel(BaseLLMModel):
    """
    A wrapper class for Google Gemini models.
    """

    def __init__(self, model_name: str = "gemini-3-pro-preview", temperature: float = 0.7, **kwargs):
        """
        Initializes the GeminiModel with the specified parameters.

        Args:
            api_key (str): The API key for authenticating with Google Gemini.
            model_name (str): The name of the Gemini model to use.
            temperature (float): The temperature setting for the model.
        """
        self.temperature = temperature
        self.model_name = model_name
        self.extra_kwargs = kwargs
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            self.api_key = getpass.getpass("Please enter your Google Gemini API Key: ")
            if not self.api_key:
                raise ValueError("Google Gemini API Key is required.")

    
    def get_chat_model(self) -> BaseChatModel:
        """
        Creates and returns a ChatGoogleGenerativeAI model instance.

        Returns:
            ChatGoogleGenerativeAI: An instance of the chat model.
        """
        return ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=self.temperature,
            api_key=self.api_key,
            **self.extra_kwargs
        )
    
    def execute(self, messages: List[BaseMessage]) -> List[dict]:
        chat_model = self.get_chat_model()
        response = chat_model.invoke(messages)

        content = response.content
        if isinstance(content, list):
            content = content[0].get("text", "") if isinstance(content[0], dict) else content[0]

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"解析 JSON 失败！原始输出内容为: {content}")
            exit()