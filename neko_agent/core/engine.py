"""Agent 执行引擎（消息循环 + 工具调用 + 自动压缩）。"""
from __future__ import annotations
import asyncio
import logging
import os
import random
from typing import Any, AsyncGenerator, Optional

from neko_agent.config import Config
from neko_agent.core.messages import (
    AssistantMessage, Message, SystemMessage, ToolCall, ToolResult, UserMessage,
    messages_to_api,
)
from neko_agent.core.tool import Tool, ToolContext, ToolRegistry
from neko_agent.core.permissions import PermissionContext, check_permission
from neko_agent.core.provider import LLMProvider, create_provider
from neko_agent.core.prompts import PromptBuilder
from neko_agent.core.compact import auto_compact_if_needed, CompactTrackingState

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 30.0
RETRYABLE_ERROR_PATTERNS = [
    "rate_limit", "overloaded", "429", "503", "502",
    "timeout", "connection", "temporarily unavailable",
]


def _is_retryable_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return any(pattern in err_str for pattern in RETRYABLE_ERROR_PATTERNS)


class Engine:
    def __init__(
        self,
        config: Config,
        registry: Optional[ToolRegistry] = None,
        tools: Optional[list[Tool]] = None,
        permission_ctx: Optional[PermissionContext] = None,
        provider: Optional[LLMProvider] = None,
        event_queue: Optional[asyncio.Queue[str]] = None,
        memory: Optional[Any] = None,
    ):
        self.config = config
        self.registry = registry or ToolRegistry()
        self.permission_ctx = permission_ctx or PermissionContext()
        self.memory = memory
        self.messages: list[Message] = []
        self.aborted = False
        self.total_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        self._compact_tracking = CompactTrackingState()
        self.event_queue = event_queue

        if provider:
            self._provider = provider
        else:
            self._provider = create_provider(
                provider=config.provider,
                api_key=config.effective_api_key,
                base_url=config.base_url,
            )

        if tools:
            for t in tools:
                self.registry.register(t)

    def _build_system_prompt(self) -> str:
        builder = PromptBuilder(self.config.cwd)
        if self.config.system_prompt:
            builder.set_domain_instructions(self.config.system_prompt)
        if self.config.append_system_prompt:
            builder.set_memory(self.config.append_system_prompt)
        builder.set_language("Chinese")
        return builder.build()

    async def _call_llm_with_retry(self, api_messages: list[dict], tool_defs: Optional[list[dict]]) -> Any:
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            if self.aborted:
                raise RuntimeError("Engine aborted")
            try:
                return await self._provider.chat(
                    messages=api_messages,
                    tools=tool_defs,
                    model=self.config.effective_model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                )
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES and _is_retryable_error(e):
                    backoff = min(INITIAL_BACKOFF_S * (2 ** attempt) + random.uniform(0, 1), MAX_BACKOFF_S)
                    logger.warning(
                        f"API error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}. Retrying in {backoff:.1f}s..."
                    )
                    await asyncio.sleep(backoff)
                else:
                    raise
        if last_error is None:
            raise RuntimeError("Unknown provider error")
        raise last_error

    async def run(self, prompt: str, max_turns: Optional[int] = None) -> AsyncGenerator[dict, None]:
        max_turns = max_turns or self.config.max_turns
        turns = 0

        if not self.messages:
            self.messages.append(SystemMessage(self._build_system_prompt()))

        attachments_text = ""
        if self.memory and prompt.strip():
            try:
                relevant = await self.memory.find_relevant(
                    query=prompt,
                    provider=self._provider,
                    model=self.config.effective_model,
                )
                if relevant:
                    attachment_docs = []
                    for m in relevant:
                        path = m.get("path")
                        if not path:
                            continue
                        content = self.memory.load_memory_content(path)
                        basename = os.path.basename(path)
                        attachment_docs.append(f"<document path=\"{basename}\">\n{content}\n</document>")
                    if attachment_docs:
                        attachments_text = (
                            "\n\n<system-reminder>\n"
                            "The following relevant memories were automatically retrieved from your persistent memory:\n"
                            + "\n".join(attachment_docs)
                            + "\n</system-reminder>\n"
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch relevant memories: {e}")

        if prompt.strip():
            self.messages.append(UserMessage(prompt + attachments_text))

        while turns < max_turns:
            turns += 1
            self._compact_tracking.turn_counter += 1

            if self.aborted:
                yield {"type": "error", "content": "Engine aborted by user"}
                return

            api_messages = messages_to_api(self.messages)
            new_messages, was_compacted = await auto_compact_if_needed(
                messages=api_messages,
                model=self.config.effective_model,
                provider=self._provider,
                tracking=self._compact_tracking,
            )
            if was_compacted:
                self.messages = [
                    SystemMessage(self._build_system_prompt()),
                    UserMessage(new_messages[0]["content"]),
                ]
                yield {"type": "compact", "content": "Conversation compacted to stay within context window."}
                api_messages = messages_to_api(self.messages)

            if self.event_queue and not self.event_queue.empty():
                while not self.event_queue.empty():
                    event_msg = self.event_queue.get_nowait()
                    self.messages.append(UserMessage(content=event_msg))
                    yield {"type": "worker_notification", "content": event_msg}
                api_messages = messages_to_api(self.messages)

            try:
                response = await self._call_llm_with_retry(api_messages, self.registry.to_api() or None)
            except Exception as e:
                yield {"type": "error", "content": f"API error: {e}"}
                return

            if response.usage:
                self.total_usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                self.total_usage["completion_tokens"] += response.usage.get("completion_tokens", 0)

            if response.thinking:
                yield {"type": "thinking", "content": response.thinking, "thinking": response.thinking}

            if not response.content and not response.tool_calls:
                logger.warning("Provider returned empty response with no tool calls.")
                yield {"type": "done", "content": "这一轮上游模型返回了空内容，你的猫儿正在重连ing..."}
                return

            assistant_msg = AssistantMessage(
                content=response.content,
                tool_calls=[ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls],
                thinking=response.thinking,
            )
            self.messages.append(assistant_msg)

            if not assistant_msg.tool_calls:
                yield {"type": "done", "content": assistant_msg.content or ""}
                return

            ctx = ToolContext(cwd=self.config.cwd, config=self.config, messages=self.messages, aborted=self.aborted)
            for tc in assistant_msg.tool_calls:
                if self.aborted:
                    yield {"type": "error", "content": "Engine aborted during tool execution"}
                    return

                yield {
                    "type": "tool_call",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "tool_call_id": tc.id,
                }

                tool_instance = self.registry.find(tc.name)
                if not tool_instance:
                    result = ToolResult(tool_call_id=tc.id, content=f"Error: unknown tool '{tc.name}'", is_error=True)
                else:
                    perm = check_permission(tool_instance, tc.arguments, self.permission_ctx)
                    if not perm.allowed:
                        result = ToolResult(tool_call_id=tc.id, content=f"Permission denied: {perm.reason}", is_error=True)
                    else:
                        try:
                            output = await tool_instance.call(tc.arguments, ctx)
                            result = ToolResult(tool_call_id=tc.id, content=output)
                        except Exception as e:
                            result = ToolResult(tool_call_id=tc.id, content=f"Tool error: {e}", is_error=True)

                self.messages.append(result)
                yield {
                    "type": "tool_result",
                    "name": tc.name,
                    "content": result.content,
                    "tool_call_id": result.tool_call_id,
                    "is_error": result.is_error,
                }

        yield {"type": "error", "content": f"Max turns ({max_turns}) reached"}

    def abort(self):
        self.aborted = True

    def reset(self):
        self.messages.clear()
        self.aborted = False
        self._compact_tracking = CompactTrackingState()
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def feed_event(self, event_msg: str):
        if self.event_queue is not None:
            self.event_queue.put_nowait(event_msg)
        else:
            self.messages.append(UserMessage(content=event_msg))
