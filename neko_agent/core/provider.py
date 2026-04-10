"""多厂商 LLM 适配层（统一 chat 接口与工具调用格式）。"""
from __future__ import annotations
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    thinking: Optional[str] = None
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)

class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        ...

class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", **kwargs):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self._extra = kwargs  # e.g. reasoning_split for MiniMax

    def _debug_enabled(self) -> bool:
        v = (os.environ.get("NEKO_DEBUG_PROVIDER", "") or "").strip().lower()
        return v in {"1", "true", "yes", "y", "on"}

    def _safe_dump(self, obj: Any) -> str:
        try:
            if hasattr(obj, "model_dump"):
                return json.dumps(obj.model_dump(), ensure_ascii=False, default=str)[:4000]
        except Exception:
            pass
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)[:4000]
        except Exception:
            return str(obj)[:4000]

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        req: dict[str, Any] = {
            "model": kwargs.get("model", "gpt-4o"),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.0),
        }
        if tools:
            req["tools"] = tools
            req["tool_choice"] = kwargs.get("tool_choice", "auto")

        for k, v in self._extra.items():
            req[k] = v

        response = await self._client.chat.completions.create(**req)

        if isinstance(response, str):
            try:
                response = json.loads(response)
            except Exception:
                return LLMResponse(content=response)

        if isinstance(response, dict):
            choices = response.get("choices") or []
            if not choices:
                return LLMResponse(
                    content=response.get("content")
                    or response.get("text")
                    or response.get("output_text")
                    or response.get("output")
                    or str(response)
                )

            choice = choices[0]
            msg = choice.get("message") or {}

            tool_calls = []
            for tc in (msg.get("tool_calls") or []):
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except Exception:
                        raw_args = {"raw": raw_args}
                tool_calls.append(LLMToolCall(
                    id=tc.get("id", "tool_call_0"),
                    name=fn.get("name", "unknown_tool"),
                    arguments=raw_args if isinstance(raw_args, dict) else {},
                ))

            content_value = msg.get("content")
            content_text = None
            if isinstance(content_value, str):
                content_text = content_value
            elif isinstance(content_value, list):
                parts = []
                for p in content_value:
                    if isinstance(p, dict):
                        t = p.get("text")
                        if not t and p.get("type") == "text":
                            t = p.get("text")
                        if t:
                            parts.append(t)
                content_text = "\n".join(parts).strip() if parts else None
            elif isinstance(content_value, dict):
                t = content_value.get("text")
                if t:
                    content_text = t

            thinking_text = msg.get("reasoning_content") or msg.get("thinking") or choice.get("reasoning_content")

            if not content_text:
                alt = None
                for k in ("output_text", "result", "response", "reply", "answer", "message", "data"):
                    v = response.get(k)
                    if isinstance(v, str) and v.strip():
                        alt = v.strip()
                        break
                    if isinstance(v, dict):
                        c = v.get("text") or v.get("content") or v.get("output_text")
                        if isinstance(c, str) and c.strip():
                            alt = c.strip()
                            break
                        if isinstance(c, list):
                            parts = []
                            for p in c:
                                if isinstance(p, str) and p.strip():
                                    parts.append(p.strip())
                                elif isinstance(p, dict):
                                    t = p.get("text") or p.get("content")
                                    if isinstance(t, str) and t.strip():
                                        parts.append(t.strip())
                            if parts:
                                alt = "\n".join(parts).strip()
                                break
                content_text = alt

            if not content_text and thinking_text:
                content_text = thinking_text
            if not content_text and not tool_calls and self._debug_enabled():
                logger.warning(
                    "Empty OpenAI-compatible response. base_url=%s model=%s raw=%s",
                    self.base_url,
                    req.get("model"),
                    self._safe_dump(response),
                )
            return LLMResponse(
                content=content_text,
                tool_calls=tool_calls,
                thinking=thinking_text,
                finish_reason=choice.get("finish_reason") or "stop",
                usage=response.get("usage") or {},
            )

        choice = response.choices[0]
        msg = choice.message

        tool_calls = []
        for tc in (msg.tool_calls or []):
            tool_calls.append(LLMToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments),
            ))

        content_text = None
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                content_text = msg.content
            elif isinstance(msg.content, list):
                parts = []
                for p in msg.content:
                    t = getattr(p, "text", None)
                    if t is None and isinstance(p, dict):
                        t = p.get("text")
                    if t:
                        parts.append(t)
                content_text = "\n".join(parts).strip() if parts else None

        thinking = getattr(msg, "reasoning_content", None) if hasattr(msg, "reasoning_content") else None
        if not thinking and hasattr(choice, "reasoning_content"):
            thinking = getattr(choice, "reasoning_content", None)

        if not content_text and thinking:
            content_text = thinking
        if not content_text and not tool_calls and self._debug_enabled():
            logger.warning(
                "Empty OpenAI-compatible response (sdk obj). base_url=%s model=%s raw=%s",
                self.base_url,
                req.get("model"),
                self._safe_dump(response),
            )
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            thinking=thinking,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
            } if response.usage else {},
        )




class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, base_url: Optional[str] = None, **kwargs):
        import anthropic
        self.base_url = base_url
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            normalized = base_url.rstrip("/")
            if normalized.endswith("/v1/messages"):
                normalized = normalized[: -len("/v1/messages")]
            elif normalized.endswith("/v1"):
                normalized = normalized[: -len("/v1")]
            client_kwargs["base_url"] = normalized
        self._client = anthropic.AsyncAnthropic(**client_kwargs)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        system_text = ""
        anthropic_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m.get("content", "")
            elif m["role"] == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m["tool_call_id"],
                        "content": m.get("content", ""),
                        "is_error": bool(m.get("is_error", False)),
                    }],
                })
            elif m["role"] == "assistant":
                content_blocks = []
                if m.get("content"):
                    content_blocks.append({"type": "text", "text": m["content"]})
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        fn = tc["function"] if isinstance(tc.get("function"), dict) else tc
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": fn["name"],
                            "input": json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"],
                        })
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                text_content = m.get("content", "")
                anthropic_messages.append({
                    "role": m["role"],
                    "content": [{"type": "text", "text": text_content}],
                })

        anthropic_tools = []
        if tools:
            for t in tools:
                fn = t["function"]
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })

        req: dict[str, Any] = {
            "model": kwargs.get("model", "claude-sonnet-4-20250514"),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": anthropic_messages,
        }
        if system_text:
            req["system"] = [{"type": "text", "text": system_text}]
        if anthropic_tools:
            req["tools"] = anthropic_tools

        response = await self._client.messages.create(**req)

        content_parts: list[str] = []
        tool_calls = []
        thinking = None

        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type is None and isinstance(block, dict):
                block_type = block.get("type")

            if block_type == "text":
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")
                if text:
                    content_parts.append(text)
            elif block_type == "thinking":
                thinking_value = getattr(block, "thinking", None)
                if thinking_value is None and isinstance(block, dict):
                    thinking_value = block.get("thinking")
                if thinking_value:
                    thinking = thinking_value
            elif block_type == "tool_use":
                tool_id = getattr(block, "id", None)
                tool_name = getattr(block, "name", None)
                tool_input = getattr(block, "input", None)
                if isinstance(block, dict):
                    tool_id = tool_id or block.get("id")
                    tool_name = tool_name or block.get("name")
                    tool_input = tool_input if tool_input is not None else block.get("input", {})
                if tool_id and tool_name:
                    tool_calls.append(LLMToolCall(
                        id=tool_id,
                        name=tool_name,
                        arguments=tool_input or {},
                    ))

        content_text = "\n".join(part for part in content_parts if part).strip()
        if not content_text and not tool_calls:
            v = (os.environ.get("NEKO_DEBUG_PROVIDER", "") or "").strip().lower()
            if v in {"1", "true", "yes", "y", "on"}:
                try:
                    payload = response.model_dump() if hasattr(response, "model_dump") else str(response)
                except Exception:
                    payload = str(response)
                logger.warning(
                    "Empty Anthropic response. base_url=%s model=%s raw=%s",
                    self.base_url,
                    req.get("model"),
                    (json.dumps(payload, ensure_ascii=False, default=str) if not isinstance(payload, str) else payload)[:4000],
                )

        return LLMResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            thinking=thinking,
            finish_reason=response.stop_reason or "stop",
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
        )


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, **kwargs):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._genai = genai

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        from google.genai import types
        import asyncio

        model = kwargs.get("model", "gemini-2.5-flash")

        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = m["content"]
            elif m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m["content"])]))
            elif m["role"] == "assistant":
                parts = []
                if m.get("content"):
                    parts.append(types.Part.from_text(text=m["content"]))
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        fn = tc["function"] if isinstance(tc.get("function"), dict) else tc
                        args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                        parts.append(types.Part.from_function_call(name=fn["name"], args=args))
                contents.append(types.Content(role="model", parts=parts))
            elif m["role"] == "tool":
                parts = [types.Part.from_function_response(
                    name="tool",
                    response={"result": m["content"]},
                )]
                contents.append(types.Content(role="user", parts=parts))

        gemini_tools = None
        if tools:
            declarations = []
            for t in tools:
                fn = t["function"]
                declarations.append(types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters"),
                ))
            gemini_tools = [types.Tool(function_declarations=declarations)]

        config = types.GenerateContentConfig(
            temperature=kwargs.get("temperature", 0.0),
            max_output_tokens=kwargs.get("max_tokens", 4096),
            tools=gemini_tools,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=model, contents=contents, config=config,
            ),
        )

        content_text = ""
        tool_calls = []
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.text:
                    content_text += part.text
                elif part.function_call:
                    fc = part.function_call
                    tool_calls.append(LLMToolCall(
                        id=f"gemini_{fc.name}_{id(fc)}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))

        return LLMResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            finish_reason="stop",
            usage={},
        )


PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai":    {"base_url": "https://api.openai.com/v1",        "model": "gpt-4o",              "env_key": "OPENAI_API_KEY"},
    "anthropic": {"base_url": "https://mix88.top",                "model": "claude-sonnet-4-5-20250929",          "env_key": "ANTHROPIC_API_KEY"},
    "gemini":    {"base_url": "",                                  "model": "gemini-2.5-flash",    "env_key": "GEMINI_API_KEY"},
    "minimax":   {"base_url": "https://api.minimaxi.com/v1",      "model": "MiniMax-M2.7",        "env_key": "MINIMAX_API_KEY"},
    "kimi":      {"base_url": "https://api.moonshot.cn/v1",        "model": "kimi-k2.5",           "env_key": "KIMI_API_KEY"},
    "moonshot":  {"base_url": "https://api.moonshot.cn/v1",        "model": "kimi-k2.5",           "env_key": "MOONSHOT_API_KEY"},
    "deepseek":  {"base_url": "https://api.deepseek.com/v1",      "model": "deepseek-reasoner",   "env_key": "DEEPSEEK_API_KEY"},
    "qwen":      {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "env_key": "QWEN_API_KEY"},
    "diy":       {"base_url": "https://mix88.top",                              "model": "claude-sonnet-4-6",        "env_key": "DIY_API_KEY"},
}


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/v1") or "/v1/" in normalized:
        return normalized
    return f"{normalized}/v1"


def _is_truthy_env(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _mask_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}...{key[-4:]}"


def _infer_diy_api_format(model: str | None) -> str:
    configured = (
        os.environ.get("DIY_API_FORMAT", "")
        or os.environ.get("DIY_PROVIDER_TYPE", "")
        or os.environ.get("DIY_PROTOCOL", "")
    ).strip().lower()
    if configured in {"anthropic", "claude"}:
        return "anthropic"
    if configured in {"openai", "oai"}:
        return "openai"

    m = (model or "").strip().lower()
    if any(x in m for x in ("claude", "sonnet", "opus", "haiku")):
        return "anthropic"
    return "openai"


class DIYAutoProvider(LLMProvider):
    name = "diy_auto"

    def __init__(self, primary: LLMProvider, secondary: LLMProvider, primary_name: str, secondary_name: str):
        self._primary = primary
        self._secondary = secondary
        self._primary_name = primary_name
        self._secondary_name = secondary_name

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        first = await self._primary.chat(messages=messages, tools=tools, **kwargs)
        if first.content or first.tool_calls:
            return first
        second = await self._secondary.chat(messages=messages, tools=tools, **kwargs)
        if second.content or second.tool_calls:
            v = (os.environ.get("NEKO_DEBUG_PROVIDER", "") or "").strip().lower()
            if v in {"1", "true", "yes", "y", "on"}:
                logger.info("DIY auto fallback: %s -> %s", self._primary_name, self._secondary_name)
            return second
        return first


def create_provider(
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
    **kwargs,
) -> LLMProvider:
    provider_lower = provider.lower()
    preset = PROVIDER_PRESETS.get(provider_lower, {})

    if provider_lower == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url, **kwargs)

    if provider_lower == "gemini":
        return GeminiProvider(api_key=api_key, **kwargs)

    if provider_lower == "diy":
        resolved_url = (
            base_url
            or preset.get("base_url")
            or os.environ.get("DIY_BASE_URL")
            or os.environ.get("DIY_URL")
            or os.environ.get("DIYBASEURL")
            or os.environ.get("DIYURL")
        )
        if not resolved_url:
            raise ValueError("DIY provider requires DIY_BASE_URL (or base_url) to be set")
        resolved_key = (api_key or "").strip()
        if not resolved_key:
            resolved_key = (
                os.environ.get("DIY_API_KEY", "")
                or os.environ.get("DIY_API", "")
                or os.environ.get("DIYAPI_KEY", "")
                or os.environ.get("DIYAPI", "")
            ).strip()
        if not resolved_key:
            raise ValueError("DIY provider requires an API key (DIY_API_KEY / DIY_API / DIYAPI_KEY / DIYAPI)")
        diy_kwargs = dict(kwargs)
        if "model" not in diy_kwargs:
            env_model = os.environ.get("DIY_MODEL", "").strip()
            if env_model:
                diy_kwargs["model"] = env_model

        model_name = (
            str(diy_kwargs.get("model") or "").strip()
            or os.environ.get("DIY_MODEL", "").strip()
            or preset.get("model", "")
        )
        configured = (
            os.environ.get("DIY_API_FORMAT", "")
            or os.environ.get("DIY_PROVIDER_TYPE", "")
            or os.environ.get("DIY_PROTOCOL", "")
        ).strip().lower()
        api_format = _infer_diy_api_format(model_name) if not configured else configured
        if _is_truthy_env(os.environ.get("NEKO_DEBUG_PROVIDER", "")):
            logger.info(
                "DIY provider resolved: api_format=%s base_url=%s model=%s api_key=%s",
                api_format,
                resolved_url,
                model_name,
                _mask_api_key(resolved_key),
            )

        if api_format == "anthropic":
            return AnthropicProvider(api_key=resolved_key, base_url=resolved_url)

        if api_format == "openai":
            resolved_url = _normalize_openai_base_url(resolved_url)
            return OpenAICompatibleProvider(api_key=resolved_key, base_url=resolved_url, **diy_kwargs)

        openai_url = _normalize_openai_base_url(resolved_url)
        openai_provider = OpenAICompatibleProvider(api_key=resolved_key, base_url=openai_url, **diy_kwargs)
        anthropic_provider = AnthropicProvider(api_key=resolved_key, base_url=resolved_url)
        if _infer_diy_api_format(model_name) == "anthropic":
            return DIYAutoProvider(
                primary=anthropic_provider,
                secondary=openai_provider,
                primary_name="anthropic",
                secondary_name="openai",
            )
        return DIYAutoProvider(
            primary=openai_provider,
            secondary=anthropic_provider,
            primary_name="openai",
            secondary_name="anthropic",
        )

    resolved_url = base_url or preset.get("base_url", "https://api.openai.com/v1")
    return OpenAICompatibleProvider(api_key=api_key, base_url=resolved_url, **kwargs)


def auto_detect_provider(api_key: str) -> tuple[str, str]:
    if api_key.startswith("sk-ant-"):
        return "anthropic", ""
    if api_key.startswith("AIza"):
        return "gemini", ""
    return "minimax", PROVIDER_PRESETS["minimax"]["base_url"]
