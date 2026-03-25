from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from abc import ABC, abstractmethod
from typing import Dict, List

class BaseLLMModel(ABC):
    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        pass

    @abstractmethod
    def execute(self, messages: List[BaseMessage]) -> List[Dict]:
        pass