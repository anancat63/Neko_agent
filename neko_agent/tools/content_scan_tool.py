"""
文本搜索工具。
使用 ripgrep 或 grep 检索文件内容，行为保持不变，但换用新的命名和说明文本。
"""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

from neko_agent.core.tool import RiskLevel, Tool, ToolContext

TOOL_KEY = "Grep"
RESULT_CAP = 100


def build_content_scan_prompt() -> str:
    return """按正则模式检索文件内容。

使用规则：
- 优先使用本工具做内容搜索，不要在 shell 里手写 grep/rg。
- 支持正则表达式，也支持按 include 过滤文件范围。
- output_mode 可选 content、files_with_matches、count。
- 多行正则可开启 multiline。
"""


def locate_search_binary() -> str:
    if shutil.which("rg"):
        return "rg"
    if shutil.which("grep"):
        return "grep"
    return ""


class ContentScanTool(Tool):
    aliases = ("grep",)
    name = TOOL_KEY
    description = build_content_scan_prompt()
    risk_level = RiskLevel.LOW
    is_read_only = True

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的正则表达式"},
                "path": {"type": "string", "description": "搜索路径，默认当前工作目录"},
                "include": {"type": "string", "description": "文件过滤模式，例如 *.py"},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "default": "content",
                    "description": "输出形式：内容、仅文件名、或统计数量",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "是否区分大小写，默认 true",
                    "default": True,
                },
                "multiline": {
                    "type": "boolean",
                    "description": "是否启用跨行匹配",
                    "default": False,
                },
            },
            "required": ["pattern"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        needle = arguments["pattern"]
        scope = arguments.get("path", context.cwd)
        if not os.path.isabs(scope):
            scope = os.path.join(context.cwd, scope)
        include_mask = arguments.get("include", "")
        mode = arguments.get("output_mode", "content")
        case_sensitive = arguments.get("case_sensitive", True)
        multiline = arguments.get("multiline", False)

        if not os.path.exists(scope):
            return f"Error: path not found: {scope}"

        binary = locate_search_binary()
        if not binary:
            return await self._python_scan(needle, scope, include_mask, mode, case_sensitive)

        try:
            if binary == "rg":
                return await self._run_rg(needle, scope, include_mask, mode, case_sensitive, multiline)
            return await self._run_grep(needle, scope, include_mask, mode, case_sensitive)
        except Exception as exc:
            return f"Error running search: {exc}"

    async def _run_rg(
        self,
        needle: str,
        scope: str,
        include_mask: str,
        mode: str,
        case_sensitive: bool,
        multiline: bool,
    ) -> str:
        cmd = ["rg", "--no-heading", "--line-number", "--color=never"]
        if not case_sensitive:
            cmd.append("-i")
        if multiline:
            cmd.append("--multiline")
        if mode == "files_with_matches":
            cmd.append("-l")
        elif mode == "count":
            cmd.append("-c")
        if include_mask:
            cmd.extend(["-g", include_mask])
        cmd.extend(["--max-count", str(RESULT_CAP), needle, scope])

        job = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(job.communicate(), timeout=30)
        rendered = stdout.decode(errors="replace").strip()
        if not rendered:
            return f"No matches found for pattern: {needle}"
        rows = rendered.split("\n")
        if len(rows) > RESULT_CAP:
            rendered = "\n".join(rows[:RESULT_CAP])
            rendered += f"\n\n... ({len(rows) - RESULT_CAP} more results not shown)"
        return rendered

    async def _run_grep(
        self,
        needle: str,
        scope: str,
        include_mask: str,
        mode: str,
        case_sensitive: bool,
    ) -> str:
        cmd = ["grep", "-rn", "--color=never"]
        if not case_sensitive:
            cmd.append("-i")
        if mode == "files_with_matches":
            cmd.append("-l")
        elif mode == "count":
            cmd.append("-c")
        if include_mask:
            cmd.extend(["--include", include_mask])
        cmd.extend([needle, scope])

        job = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(job.communicate(), timeout=30)
        rendered = stdout.decode(errors="replace").strip()
        if not rendered:
            return f"No matches found for pattern: {needle}"
        rows = rendered.split("\n")
        if len(rows) > RESULT_CAP:
            rendered = "\n".join(rows[:RESULT_CAP])
            rendered += f"\n\n... ({len(rows) - RESULT_CAP} more results not shown)"
        return rendered

    async def _python_scan(
        self,
        needle: str,
        scope: str,
        include_mask: str,
        mode: str,
        case_sensitive: bool,
    ) -> str:
        import glob as py_glob
        import re

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            matcher = re.compile(needle, flags)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"

        if os.path.isfile(scope):
            candidates = [scope]
        else:
            mask = include_mask if include_mask else "**/*"
            candidates = [
                item for item in py_glob.glob(os.path.join(scope, mask), recursive=True)
                if os.path.isfile(item)
            ]

        collected: list[str] = []
        total_hits = 0
        for item in candidates:
            try:
                with open(item, "r", encoding="utf-8", errors="replace") as handle:
                    for line_no, line in enumerate(handle, 1):
                        if not matcher.search(line):
                            continue
                        if mode == "files_with_matches":
                            collected.append(item)
                            break
                        if mode == "count":
                            total_hits += 1
                        else:
                            collected.append(f"{item}:{line_no}:{line.rstrip()}")
                        if len(collected) >= RESULT_CAP:
                            break
            except (OSError, UnicodeDecodeError):
                continue
            if len(collected) >= RESULT_CAP:
                break

        if mode == "count":
            return f"Match count: {total_hits}"
        if not collected:
            return f"No matches found for pattern: {needle}"
        return "\n".join(collected)
