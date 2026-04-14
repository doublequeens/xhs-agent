import json
from typing import List

from langchain_deepseek import ChatDeepSeek
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from src.models.base import BaseLLMModel
import os, getpass

class DeepSeekModel(BaseLLMModel):
    def __init__(self, model_name: str = "deepseek-reasoner", tools: list = None, temperature: float = 1.3, **kwargs):
        self._chat_model = None
        self.model_name = model_name
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.temperature = temperature
        self.tools = tools
        self.extra_kwargs = kwargs
        if not self.api_key:
            self.api_key = getpass.getpass("Please enter your DeepSeek API Key: ")
            if not self.api_key:
                raise ValueError("DeepSeek API Key is required.")

    def get_chat_model(self) -> BaseChatModel:
        """
        Creates and returns a ChatDeepSeek model instance.

        Returns:
            ChatDeepSeek: An instance of the chat model.
        """
        if self._chat_model is None:
            model = ChatDeepSeek(
                model=self.model_name,
                api_key=self.api_key,
                temperature=self.temperature,
                **self.extra_kwargs
            )
            if self.tools:
                model = model.bind_tools(self.tools)
            self._chat_model = model
            
        return self._chat_model
    
    def execute(self, messages: List[BaseMessage]) -> dict:
        chat_model = self.get_chat_model()
        response = chat_model.invoke(messages)

        content = response.content

        # Clean up potential markdown code block wrappers from the response
        content = str(content).strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"解析 JSON 失败！原始输出内容为: {content}")
            exit()