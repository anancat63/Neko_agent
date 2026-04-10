"""工具抽象（Tool/Registry/Context）与 @tool 装饰器。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from neko_agent.config import Config
    from neko_agent.core.permissions import PermissionContext


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PermissionCheck:
    allowed: bool
    reason: str = ""


class Tool(ABC):
    name: str = ""
    aliases: tuple[str, ...] = ()
    description: str = ""
    parameters: Optional[dict[str, Any]] = None
    risk_level: RiskLevel = RiskLevel.LOW
    is_read_only: bool = True
    is_destructive: bool = False

    def get_parameters(self) -> dict:
        if self.parameters is not None:
            return self.parameters
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        ...

    def check_permissions(self, arguments: dict[str, Any], context: PermissionContext) -> PermissionCheck:
        return PermissionCheck(allowed=True)

    def to_api(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters(),
            },
        }


@dataclass
class ToolContext:
    cwd: str = "."
    config: Optional[Config] = None
    messages: list = field(default_factory=list)
    depth: int = 0
    aborted: bool = False


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool_instance: Tool) -> Tool:
        self._tools[tool_instance.name] = tool_instance
        for alias in getattr(tool_instance, "aliases", ()):
            self._tools[alias] = tool_instance
        return tool_instance

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        seen: dict[int, Tool] = {}
        for tool in self._tools.values():
            seen[id(tool)] = tool
        return list(seen.values())

    def to_api(self) -> list[dict]:
        return [t.to_api() for t in self.all()]

    def find(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)


_default_registry = ToolRegistry()


def tool(
    name: str,
    description: str = "",
    parameters: Optional[dict] = None,
    risk_level: RiskLevel = RiskLevel.LOW,
    is_read_only: bool = True,
    registry: Optional[ToolRegistry] = None,
):
    reg = registry or _default_registry

    def decorator(fn: Callable) -> Tool:
        class FnTool(Tool):
            pass

        instance = FnTool()
        instance.name = name
        instance.description = description or fn.__doc__ or ""
        instance.risk_level = risk_level
        instance.is_read_only = is_read_only
        instance._parameters = parameters or {"type": "object", "properties": {}}
        instance._fn = fn

        def get_parameters(self_inner) -> dict:
            return self_inner._parameters

        async def call_fn(self_inner, arguments: dict[str, Any], context: ToolContext) -> str:
            return await self_inner._fn(arguments, context)

        setattr(instance, "get_parameters", get_parameters.__get__(instance))
        setattr(instance, "call", call_fn.__get__(instance))

        reg.register(instance)
        return instance

    return decorator
