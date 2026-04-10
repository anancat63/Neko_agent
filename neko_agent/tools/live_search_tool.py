"""
联网搜索工具。
使用公开搜索页抓取网页结果，输出标题、摘要和链接。
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote

import httpx

from neko_agent.core.tool import RiskLevel, Tool, ToolContext


class LiveSearchTool(Tool):
    name = "web_search"
    description = "联网搜索当前信息，返回标题、摘要和链接列表。适合需要外部资料的问题。"
    risk_level = RiskLevel.LOW
    is_read_only = True

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条结果，默认 5，最大 10",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def call(self, arguments: dict[str, Any], context: ToolContext) -> str:
        keyword = arguments["query"].strip()
        top_k = max(1, min(int(arguments.get("limit", 5)), 10))
        if not keyword:
            return "Error: query cannot be empty"

        search_url = f"https://html.duckduckgo.com/html/?q={quote(keyword)}"
        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                response = await client.get(search_url, headers=request_headers)
                response.raise_for_status()
        except Exception as exc:
            return f"Error performing web search: {exc}"

        items = self._collect_results(response.text, top_k)
        if not items:
            return "No search results found."

        rows = [f"Search results for: {keyword}"]
        for index, item in enumerate(items, start=1):
            rows.append(f"{index}. {item['title']}")
            rows.append(f"   URL: {item['url']}")
            if item["snippet"]:
                rows.append(f"   Snippet: {item['snippet']}")
        return "\n".join(rows)

    def _collect_results(self, page_html: str, top_k: int) -> list[dict[str, str]]:
        collected: list[dict[str, str]] = []
        link_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>(?P<tail>.*?)'
            r'(?=<a[^>]*class="result__a"|$)',
            re.DOTALL,
        )
        snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL)

        for match in link_pattern.finditer(page_html):
            url = html.unescape(match.group("url")).strip()
            title = self._strip_markup(match.group("title"))
            tail = match.group("tail")
            snippet_match = snippet_pattern.search(tail)
            snippet = self._strip_markup(snippet_match.group("snippet")) if snippet_match else ""
            if not title or not url:
                continue
            collected.append({"title": title, "url": url, "snippet": snippet})
            if len(collected) >= top_k:
                break
        return collected

    def _strip_markup(self, raw_text: str) -> str:
        text = re.sub(r"<.*?>", " ", raw_text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
