from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, ToolMessage
from typing import List
from .base import BaseLLMModel
from ._guard import invoke_with_hard_timeout
import os, getpass
import warnings
import json_repair

# 忽略由于智谱 API Key secret 长度不足 32 字节而导致的 PyJWT 警告
warnings.filterwarnings("ignore", message=".*The HMAC key is.*")

class ZhipuModel(BaseLLMModel):
    """
    A wrapper class for Zhipu AI models.
    """

    def __init__(self, model_name: str = "GLM-5.3", temperature: float = 0.95, tools: list = None, **kwargs):
        """
        Initializes the ZhipuModel with the specified parameters.

        Args:
            model_name (str): The name of the Zhipu model to use.
            temperature (float): The temperature setting for the model.
            tools (list): A list of tools to bind to the model.
        """
        self._chat_model = None
        self.temperature = temperature
        self.model_name = model_name
        self.api_key = os.getenv("ZHIPUAI_API_KEY")
        self.tools = tools
        self.extra_kwargs = kwargs
        if not self.api_key:
            self.api_key = getpass.getpass("Please enter your Zhipu API Key: ")
            if not self.api_key:
                raise ValueError("Zhipu API Key is required.")

    def get_chat_model(self):
        """
        Creates and returns a ChatOpenAI model instance configured for Zhipu API.

        Returns:
            ChatOpenAI: An instance of the chat model.
        """
        if self._chat_model is None:
            model = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url="https://open.bigmodel.cn/api/coding/paas/v4/",
                timeout=480,
                temperature=self.temperature,
                max_retries=0,
                # GLM thinking models generate for minutes before the first
                # byte in non-streaming mode, and the provider gateway drops
                # idle non-streaming connections long before that (measured:
                # zero-byte stall until the 480s hard timeout on
                # angle_strategist-scale prompts, 2026-08-29).  Streaming
                # keeps bytes flowing during thinking; langchain aggregates
                # the chunks into the same response object.
                streaming=True,
                **self.extra_kwargs
            )
            if self.tools:
                model = model.bind_tools(self.tools)
            self._chat_model = model
        return self._chat_model
    
    def execute(self, messages: List[BaseMessage]) -> List[dict]:
        chat_model = self.get_chat_model()
        # GLM-5.3 thinking generations legitimately run long: measured
        # angle-strategist-scale prompts complete in 396-463s, and slow
        # samples exceed 480s while still streaming.  The budget must sit
        # above the real generation envelope so only true hangs are cut;
        # streaming (see get_chat_model) already prevents idle-gateway
        # stalls, so a generous wall-clock cap is safe here.
        response = invoke_with_hard_timeout(chat_model, messages, hard_timeout=900)

        if self.tools and response.tool_calls:
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
            response = invoke_with_hard_timeout(chat_model, messages, hard_timeout=900)


        content = response.content
        # Clean up potential markdown code block wrappers from the response
        # content = str(content).strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json_repair.loads(content)
        except Exception as e:
            raise ValueError(f"Failed to parse JSON from model response: {e}. Content: {content}")
