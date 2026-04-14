import json
import os, getpass
from typing import List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from src.models.base import BaseLLMModel
from langchain.agents import create_agent



class GeminiModel(BaseLLMModel):
    """
    A wrapper class for Google Gemini models.
    """

    def __init__(self, model_name: str = "gemini-3.1-pro-preview",  temperature: float = 0.7, tools: list = None, **kwargs):
        """
        Initializes the GeminiModel with the specified parameters.

        Args:
            api_key (str): The API key for authenticating with Google Gemini.
            model_name (str): The name of the Gemini model to use.
            temperature (float): The temperature setting for the model.
        """
        self._chat_model = None
        self.temperature = temperature
        self.model_name = model_name
        self.api_key = None
        self.extra_kwargs = kwargs
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.tools = tools
        if not self.api_key:
            self.api_key = getpass.getpass("Please enter your Google Gemini API Key: ")
            if not self.api_key:
                raise ValueError("Google Gemini API Key is required.")

    
    def get_chat_model(self) -> BaseChatModel:
        """
        Creates and returns a ChatGoogleGenerativeAI model instance.

        Returns:
            ChatGoogleGenerativeAI: An instance of the chat model.
        """
        if self._chat_model is None:
            model = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                api_key=self.api_key,
                **self.extra_kwargs
            )
            if self.tools:
                model = model.bind_tools(self.tools)
            self._chat_model = model
        return self._chat_model
    
    def execute(self, messages: List[BaseMessage]) -> List[dict]:
        
        chat_model = self.get_chat_model()
        response = chat_model.invoke(messages)

        if response.tool_calls and self.tools:
            messages.append(response)
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                tool_instance = next((t for t in self.tools if getattr(t, "name", "") == tool_name), None)
                if tool_instance:
                    print(f"Executing tool: {tool_name} ...")
                    tool_response = tool_instance.invoke(tool_args)
                    messages.append(ToolMessage(
                        content=str(tool_response), 
                        name=tool_name,
                        tool_call_id=tool_id
                    ))
            
            # 等所有 tool_calls 对应的 ToolMessage 都追加完之后，再次统一请求大模型
            response = chat_model.invoke(messages)

        content = response.content
        if isinstance(content, list):
            content = content[0].get("text", "") if isinstance(content[0], dict) else content[0]

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