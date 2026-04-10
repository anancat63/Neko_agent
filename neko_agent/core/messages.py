"""统一消息结构与 API 格式转换。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import json


@dataclass
class UserMessage:
    content: str
    role: str = "user"

    def to_api(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class AssistantMessage:
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: Optional[str] = None
    role: str = "assistant"

    def to_api(self) -> dict:
        msg: dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [tc.to_api() for tc in self.tool_calls]
        return msg


@dataclass
class SystemMessage:
    content: str
    role: str = "system"

    def to_api(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_api(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    role: str = "tool"

    def to_api(self) -> dict:
        payload = {
            "role": self.role,
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }
        if self.is_error:
            payload["is_error"] = True
        return payload


Message = UserMessage | AssistantMessage | SystemMessage | ToolResult


def messages_to_api(messages: list[Message]) -> list[dict]:
    return [m.to_api() for m in messages]
