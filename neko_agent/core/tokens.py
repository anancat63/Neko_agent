"""Token 估算（启发式）。"""
from __future__ import annotations
import json
from typing import Any


CHARS_PER_TOKEN_TEXT = 4.0
CHARS_PER_TOKEN_CODE = 3.5

TOOL_CALL_OVERHEAD = 50

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-opus": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4.1": 1_048_576,
    "gpt-4.1-mini": 1_048_576,
    "o3": 200_000,
    "o4-mini": 200_000,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    "MiniMax-M2.7": 1_048_576,
    "kimi-k2.5": 131_072,
    "qwen-plus": 131_072,
}

DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model: str) -> int:
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    model_lower = model.lower()
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if model_lower.startswith(key.lower().split("-")[0]):
            return window

    return DEFAULT_CONTEXT_WINDOW


def estimate_tokens_text(text: str) -> int:
    if not text:
        return 0

    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f')
    non_cjk_len = len(text) - cjk_count

    tokens = non_cjk_len / CHARS_PER_TOKEN_TEXT + cjk_count / 1.5
    return max(1, int(tokens))


def estimate_tokens_message(message: dict[str, Any]) -> int:
    tokens = 4

    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens_text(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "") or part.get("content", "")
                if text:
                    tokens += estimate_tokens_text(str(text))
                if part.get("type") == "image":
                    tokens += 1000
            else:
                tokens += estimate_tokens_text(str(part))

    tool_calls = message.get("tool_calls", [])
    for tc in tool_calls:
        tokens += TOOL_CALL_OVERHEAD
        fn = tc.get("function", tc)
        if isinstance(fn, dict):
            args = fn.get("arguments", "")
            if isinstance(args, str):
                tokens += estimate_tokens_text(args)
            elif isinstance(args, dict):
                tokens += estimate_tokens_text(json.dumps(args))

    return tokens


def estimate_tokens_messages(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens_message(m) for m in messages)
