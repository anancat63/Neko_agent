"""
文件读写工具集合。
保留原有文件读取、精确替换和整文件写入能力，仅调整命名和说明文字。
"""
from __future__ import annotations

import os
from typing import Any

from neko_agent.core.tool import RiskLevel, Tool, ToolContext

READ_TOOL_KEY = "file_read"
EDIT_TOOL_KEY = "file_edit"
WRITE_TOOL_KEY = "file_write"
MAX_READ_LINES = 2000
UNCHANGED_HINT = (
    "文件自上次读取后没有变化，可继续参考本轮较早的读取结果，无需重复读取。"
)


def build_file_read_prompt() -> str:
    return f"""读取本地文件内容。

使用规则：
- file_path 最好传绝对路径；若传相对路径，会自动基于当前工作目录解析。
- 默认最多读取 {MAX_READ_LINES} 行，可结合 offset 和 limit 分段查看大文件。
- 返回内容会附带行号，便于后续精确编辑。
- 这个工具可以读取普通文本文件；目录请交给 shell 或其他列目录工具处理。
- 若文件为空，会直接提示为空文件。
"""


class FilePeekTool(Tool):
    name = READ_TOOL_KEY
    description = build_file_read_prompt()
    risk_level = RiskLevel.LOW
    is_read_only = True

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件路径",
                },
                "offset": {
                    "type": "integer",
                    "description": "从第几行开始读取，默认 0",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": f"最多读取多少行，默认 {MAX_READ_LINES}",
                    "default": MAX_READ_LINES,
                },
            },
            "required": ["file_path"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        target_path = arguments["file_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(context.cwd, target_path)

        start_line = arguments.get("offset", 0)
        max_lines = arguments.get("limit", MAX_READ_LINES)

        if not os.path.exists(target_path):
            return f"Error: file not found: {target_path}"
        if os.path.isdir(target_path):
            return f"Error: {target_path} is a directory, not a file."

        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as handle:
                all_lines = handle.readlines()

            total_lines = len(all_lines)
            if total_lines == 0:
                return "(empty file — this file exists but has no content)"

            begin = max(0, start_line)
            chosen_lines = all_lines[begin : begin + max_lines]
            numbered_rows = [
                f"  {line_no}\t{text.rstrip()}"
                for line_no, text in enumerate(chosen_lines, start=begin + 1)
            ]
            rendered = "\n".join(numbered_rows)
            if total_lines > begin + max_lines:
                rendered += f"\n\n... ({total_lines - begin - max_lines} more lines not shown)"
            return rendered
        except Exception as exc:
            return f"Error reading file: {exc}"


def build_file_edit_prompt() -> str:
    return """对文件内容执行精确字符串替换。

使用规则：
- 编辑前应先读取文件，确保 old_string 完整且精确。
- old_string 默认必须唯一；若存在多处匹配且确实都要改，请开启 replace_all。
- 修改时必须保留正确缩进和换行风格。
- 优先修改现有文件，除非用户明确要求新建文件。
"""


class FilePatchTool(Tool):
    name = EDIT_TOOL_KEY
    description = build_file_edit_prompt()
    risk_level = RiskLevel.MEDIUM
    is_read_only = False

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要编辑的文件路径",
                },
                "old_string": {
                    "type": "string",
                    "description": "需要被替换的原始文本",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的文本",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        target_path = arguments["file_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(context.cwd, target_path)

        before_text = arguments["old_string"]
        after_text = arguments["new_string"]
        replace_all = arguments.get("replace_all", False)

        if not os.path.exists(target_path):
            return f"Error: file not found: {target_path}"

        try:
            with open(target_path, "r", encoding="utf-8") as handle:
                source = handle.read()

            hit_count = source.count(before_text)
            if hit_count == 0:
                return "Error: old_string not found in file. Make sure the text matches exactly, including whitespace and line endings."
            if hit_count > 1 and not replace_all:
                return (
                    f"Error: old_string found {hit_count} times — must be unique. "
                    f"Provide more surrounding context to make it unique, or set replace_all=true."
                )

            updated = source.replace(before_text, after_text) if replace_all else source.replace(before_text, after_text, 1)
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(updated)

            applied = hit_count if replace_all else 1
            suffix = "s" if applied > 1 else ""
            return f"Successfully edited {target_path} ({applied} replacement{suffix})"
        except Exception as exc:
            return f"Error editing file: {exc}"


def build_file_write_prompt() -> str:
    return """将内容完整写入本地文件。

使用规则：
- 若目标文件已存在，会被整体覆盖。
- 修改现有文件时，优先使用精确替换工具；本工具更适合新建文件或整文件重写。
- 会自动创建缺失的父目录。
"""


class FileSaveTool(Tool):
    name = WRITE_TOOL_KEY
    description = build_file_write_prompt()
    risk_level = RiskLevel.MEDIUM
    is_read_only = False

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要写入的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "完整文件内容",
                },
            },
            "required": ["file_path", "content"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        target_path = arguments["file_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(context.cwd, target_path)
        payload = arguments["content"]

        try:
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
            return f"Successfully wrote {len(payload)} chars to {target_path}"
        except Exception as exc:
            return f"Error writing file: {exc}"
