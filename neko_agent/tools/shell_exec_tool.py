"""
终端命令工具集合。
提供一个受超时控制的 shell 执行器，保留原有能力，但改用新的命名与说明文本。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from neko_agent.core.permissions import is_dangerous_command
from neko_agent.core.tool import PermissionCheck, RiskLevel, Tool, ToolContext

TOOL_KEY = "Exec"
DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600


def build_shell_tool_prompt() -> str:
    return """执行一条 shell 命令并返回输出。

使用规则：
- 优先用专用工具完成文件搜索、内容搜索、读写文件，不要把这些事情都塞进 shell。
- 只有在确实需要系统命令、git、进程操作、包管理或脚本执行时，才使用本工具。
- 如果路径里包含空格，请用双引号包裹。
- 多条相互依赖的命令请用 && 串联；互不依赖时应拆成多次工具调用。
- timeout 单位是秒，默认 120，最大 600。
- run_in_background=true 时只负责启动，不等待结果。
- 未经用户明确要求，不要执行高风险破坏性命令。
"""


class ShellExecTool(Tool):
    name = TOOL_KEY
    description = build_shell_tool_prompt()
    risk_level = RiskLevel.HIGH
    is_read_only = False

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"超时时间，单位秒，默认 {DEFAULT_TIMEOUT_S}，最大 {MAX_TIMEOUT_S}",
                    "default": DEFAULT_TIMEOUT_S,
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "是否后台启动命令并立即返回",
                    "default": False,
                },
            },
            "required": ["command"],
        }

    def check_permissions(self, arguments: dict[str, Any], config: Any) -> PermissionCheck:
        raw_command = arguments.get("command", "")
        if is_dangerous_command(raw_command):
            return PermissionCheck(allowed=False, reason=f"Dangerous command blocked: {raw_command[:80]}")
        return PermissionCheck(allowed=True)

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        raw_command = arguments["command"]
        timeout_seconds = min(arguments.get("timeout", DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S)
        launch_only = arguments.get("run_in_background", False)

        try:
            child = await asyncio.create_subprocess_shell(
                raw_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.cwd,
                env={**os.environ},
            )

            if launch_only:
                return f"Command started in background (PID: {child.pid})"

            stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=timeout_seconds)

            chunks: list[str] = []
            if stdout:
                chunks.append(stdout.decode(errors="replace"))
            if stderr:
                chunks.append(f"[stderr]\n{stderr.decode(errors='replace')}")
            if child.returncode != 0:
                chunks.append(f"[exit code: {child.returncode}]")

            return "\n".join(chunks) if chunks else "(no output)"
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout_seconds}s"
        except Exception as exc:
            return f"Error executing command: {exc}"
