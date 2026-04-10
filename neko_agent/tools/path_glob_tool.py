"""
路径匹配工具。
用于按文件名模式快速定位工作区中的文件，保留原有 glob 匹配行为。
"""
from __future__ import annotations

import glob as std_glob
import os
from typing import Any

from neko_agent.core.tool import RiskLevel, Tool, ToolContext

TOOL_KEY = "Glob"
RESULT_CAP = 100


def build_path_glob_prompt() -> str:
    return """按文件名模式查找文件。

使用规则：
- 支持 **/*.py、src/**/*.ts 这类 glob 模式。
- 默认只返回文件，不返回目录。
- 结果会按最近修改时间排序，新的排前面。
- 适合在不知道精确文件名、但知道命名规律时使用。
"""


class PathPatternTool(Tool):
    name = TOOL_KEY
    description = build_path_glob_prompt()
    risk_level = RiskLevel.LOW
    is_read_only = True

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "文件匹配模式，例如 **/*.py",
                },
                "path": {
                    "type": "string",
                    "description": "搜索起点目录，默认当前工作目录",
                },
            },
            "required": ["pattern"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        mask = arguments["pattern"]
        base_dir = arguments.get("path", context.cwd)
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(context.cwd, base_dir)

        if not os.path.isdir(base_dir):
            return f"Error: directory not found: {base_dir}"

        try:
            absolute_pattern = os.path.join(base_dir, mask)
            matched_entries = std_glob.glob(absolute_pattern, recursive=True)
            matched_files = [item for item in matched_entries if os.path.isfile(item)]
            matched_files.sort(key=lambda item: os.path.getmtime(item), reverse=True)

            if not matched_files:
                return f"No files found matching pattern: {mask}"

            visible_files = matched_files[:RESULT_CAP]
            lines: list[str] = []
            for item in visible_files:
                try:
                    lines.append(os.path.relpath(item, base_dir))
                except ValueError:
                    lines.append(item)

            output = "\n".join(lines)
            if len(matched_files) > RESULT_CAP:
                hidden = len(matched_files) - RESULT_CAP
                output += f"\n\n... ({hidden} more files not shown, {len(matched_files)} total matches)"
            return output
        except Exception as exc:
            return f"Error running glob: {exc}"
