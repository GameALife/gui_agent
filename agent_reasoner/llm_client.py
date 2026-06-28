"""统一 LLM 客户端。

默认走 OpenAI-compatible Chat Completions 协议，保持 DeepSeek 可直接使用；
也可以通过 LLM_PROVIDER=litellm 切到 LiteLLM，以复用它对更多模型供应商的适配。
"""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Protocol

import requests


class ChatProvider(Protocol):
    """模型供应商适配器的最小接口。"""

    def chat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        max_retries: int,
    ) -> str:
        ...


@dataclass
class LLMConfig:
    """LLM 运行配置。"""

    provider: str = "openai_compatible"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = ""
    timeout: float = 60.0

    @classmethod
    def from_env(
        cls,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> "LLMConfig":
        """从环境变量构建配置，兼容旧的 DEEPSEEK_* 变量。"""
        resolved_provider = (
            provider
            or os.getenv("LLM_PROVIDER")
            or os.getenv("MODEL_PROVIDER")
            or "openai_compatible"
        ).strip()
        provider_key = resolved_provider.lower()
        resolved_model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or ("deepseek/deepseek-chat" if provider_key in ("litellm", "lite_llm") else "deepseek-chat")
        ).strip()
        resolved_api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or ""
        )
        resolved_base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL")
            or cls._default_base_url(resolved_provider)
        ).rstrip("/")
        resolved_timeout = timeout or float(os.getenv("LLM_TIMEOUT", "60"))
        return cls(
            provider=resolved_provider,
            model=resolved_model,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=resolved_timeout,
        )

    @staticmethod
    def _default_base_url(provider: str) -> str:
        provider = provider.lower()
        if provider == "openai":
            return "https://api.openai.com/v1"
        if provider in ("litellm", "lite_llm"):
            return ""
        return "https://api.deepseek.com"


class OpenAICompatibleProvider:
    """直接调用 OpenAI-compatible /chat/completions 接口。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        if not config.base_url:
            raise ValueError("openai_compatible/deepseek provider 必须配置 LLM_BASE_URL。")
        self.chat_url = self._normalize_chat_url(config.base_url)

        if not config.api_key and self._requires_api_key(config.base_url):
            raise ValueError(
                "LLM API key 未设置。请设置 LLM_API_KEY/OPENAI_API_KEY/DEEPSEEK_API_KEY，"
                "或在本地无鉴权模型服务上配置 LLM_BASE_URL。"
            )

    def chat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        max_retries: int,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.chat_url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout,
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = min(2 ** attempt, 8)
                    print(f"LLM 请求暂时失败({resp.status_code})，{wait}s 后重试 "
                          f"({attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return self._extract_content(resp.json())
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait = min(2 ** attempt, 8)
                    print(f"LLM 网络异常，{wait}s 后重试 ({attempt + 1}/{max_retries})：{exc}")
                    time.sleep(wait)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("LLM 请求多次重试后仍未成功。")

    @staticmethod
    def _normalize_chat_url(base_url: str) -> str:
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/chat/completions"

    @staticmethod
    def _requires_api_key(base_url: str) -> bool:
        return not re.search(r"//(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?(/|$)", base_url)

    @staticmethod
    def _extract_content(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"LLM 响应格式不符合 chat completions：{data}") from exc


class LiteLLMProvider:
    """通过 LiteLLM 调用任意兼容模型。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        try:
            import litellm  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "已配置 LLM_PROVIDER=litellm，但当前环境没有安装 litellm。"
                "请安装 litellm，或改用 LLM_PROVIDER=openai_compatible。"
            ) from exc
        self._litellm = litellm

    def chat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        max_retries: int,
    ) -> str:
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": self.config.timeout,
        }
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["api_base"] = self.config.base_url

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self._litellm.completion(**kwargs)
                return response["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait = min(2 ** attempt, 8)
                    print(f"LiteLLM 调用失败，{wait}s 后重试 "
                          f"({attempt + 1}/{max_retries})：{exc}")
                    time.sleep(wait)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("LiteLLM 请求多次重试后仍未成功。")


class LLMClient:
    """统一模型 API 封装。

    公开方法保持为 chat/chat_json，推理层和执行层不需要关心具体供应商。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout: float | None = None,
    ):
        self.config = LLMConfig.from_env(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.provider = self._build_provider(self.config)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        max_retries: int = 3,
    ) -> str:
        """发送聊天请求，返回助手回复文本。"""
        return self.provider.chat(messages, temperature, max_tokens, max_retries)

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        max_retries: int = 3,
    ) -> dict:
        """发送聊天请求并解析 JSON 响应。"""
        text = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        return self._extract_json(text)

    @staticmethod
    def _build_provider(config: LLMConfig) -> ChatProvider:
        provider = config.provider.lower()
        if provider in ("litellm", "lite_llm"):
            return LiteLLMProvider(config)
        if provider in ("openai", "openai_compatible", "deepseek", "compatible"):
            return OpenAICompatibleProvider(config)
        raise ValueError(
            f"不支持的 LLM_PROVIDER={config.provider}。"
            "可选：openai_compatible / deepseek / litellm。"
        )

    @staticmethod
    def _extract_json(text: str) -> dict:
        """从 LLM 回复中提取 JSON，兼容代码块、解释文本和双花括号。"""
        normalized = _normalize_json_text(text)

        candidates = [normalized]
        fenced = _extract_fenced_json(normalized)
        if fenced:
            candidates.insert(0, fenced)

        obj_text = _find_first_json_object(normalized)
        if obj_text:
            candidates.append(obj_text)

        errors = []
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
                errors.append(f"JSON 顶层不是对象：{type(parsed).__name__}")
            except json.JSONDecodeError as exc:
                errors.append(str(exc))

        raise ValueError(f"无法从 LLM 回复中解析 JSON。错误：{'; '.join(errors)}\n原始回复：\n{text}")


def _normalize_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("{{") and "}}" in text:
        text = text.replace("{{", "{", 1)
        last_brace = text.rfind("}}")
        if last_brace >= 0:
            text = text[:last_brace] + "}" + text[last_brace + 2:]
    return text


def _extract_fenced_json(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _find_first_json_object(text: str) -> str | None:
    """用 JSONDecoder 从任意文本中找到第一个 JSON 对象，避免正则贪婪误伤。"""
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[idx:])
            if isinstance(parsed, dict):
                return text[idx:idx + end]
        except json.JSONDecodeError:
            continue
    return None
