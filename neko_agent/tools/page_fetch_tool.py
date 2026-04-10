"""
网页抓取工具。
负责拉取指定 URL 的响应文本，保留原有 HTTP 抓取能力。
"""
from __future__ import annotations

from typing import Any

import httpx

from neko_agent.core.tool import RiskLevel, Tool, ToolContext


class PageFetchTool(Tool):
    name = "web_fetch"
    description = "抓取指定 URL 的内容，并返回响应文本。适合在已知页面地址时读取原始页面。"
    risk_level = RiskLevel.LOW
    is_read_only = True

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要访问的网页地址"},
                "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                "headers": {"type": "object", "description": "可选请求头"},
            },
            "required": ["url"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        target_url = arguments["url"]
        http_method = arguments.get("method", "GET")
        extra_headers = arguments.get("headers", {})

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.request(http_method, target_url, headers=extra_headers)
                body = response.text[:50_000]
                if len(response.text) > 50_000:
                    body += f"\n... (truncated, {len(response.text)} total chars)"
                return f"[{response.status_code}]\n{body}"
        except Exception as exc:
            return f"Error fetching URL: {exc}"
