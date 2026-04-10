"""子代理运行与子代理工具。"""
from __future__ import annotations
from typing import Optional

from neko_agent.config import Config
from neko_agent.core.engine import Engine
from neko_agent.core.tool import Tool, ToolContext, ToolRegistry, RiskLevel


async def run_sub_agent(
    prompt: str,
    config: Config,
    tools: Optional[list[Tool]] = None,
    max_turns: int = 20,
    system_prompt: Optional[str] = None,
) -> str:
    sub_config = Config(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        max_turns=max_turns,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        cwd=config.cwd,
        system_prompt=system_prompt,
    )

    registry = ToolRegistry()
    engine = Engine(config=sub_config, registry=registry, tools=tools)

    output_parts = []
    async for event in engine.run(prompt, max_turns=max_turns):
        if event["type"] == "done":
            output_parts.append(event["content"])
        elif event["type"] == "error":
            output_parts.append(f"[sub-agent error] {event['content']}")

    return "\n".join(output_parts) if output_parts else "(no output from sub-agent)"


class AgentTool(Tool):
    name = "agent"
    description = "Spawn an independent sub-agent to handle a complex sub-task. The sub-agent has its own conversation and tools."
    risk_level = RiskLevel.MEDIUM
    is_read_only = False

    def __init__(self, available_tools: Optional[list[Tool]] = None):
        self._tools = available_tools

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task description for the sub-agent / 子代理的任务描述",
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Max turns for the sub-agent (default: 20)",
                    "default": 20,
                },
            },
            "required": ["prompt"],
        }

    async def call(self, arguments: dict, context: ToolContext) -> str:
        prompt = arguments["prompt"]
        max_turns = arguments.get("max_turns", 20)

        if not context.config:
            return "Error: no config available for sub-agent"

        return await run_sub_agent(
            prompt=prompt,
            config=context.config,
            tools=self._tools,
            max_turns=max_turns,
        )
