"""命令行入口（交互式 REPL）。"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from neko_agent.config import Config
from neko_agent.core.engine import Engine
from neko_agent.core.mcp_client import MCPManager, MCPServerConfig
from neko_agent.core.provider import PROVIDER_PRESETS
from neko_agent.tools import get_default_tools
from neko_agent.memory.memory import Memory


console = Console()
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    load_dotenv()

BRAND_GREEN = "#27d16f"
USER_BLUE = "#4da3ff"
ASSISTANT_GREEN = "#1fa85a"
USER_PROMPT = f"[bold {USER_BLUE}]> [/bold {USER_BLUE}]"
ASSISTANT_PROMPT = f"[bold {ASSISTANT_GREEN}]^･֊･^ ੭ : [/bold {ASSISTANT_GREEN}]"
SHIBUYA_NEKO_LOGO = r"""
[#27d16f]
 ███████╗██╗  ██╗██╗██████╗ ██╗   ██╗██╗   ██╗ █████╗ ███╗   ██╗███████╗██╗  ██╗ ██████╗
 ██╔════╝██║  ██║██║██╔══██╗██║   ██║╚██╗ ██╔╝██╔══██╗████╗  ██║██╔════╝██║ ██╔╝██╔═══██╗
 ███████╗███████║██║██████╔╝██║   ██║ ╚████╔╝ ███████║██╔██╗ ██║█████╗  █████╔╝ ██║   ██║
 ╚════██║██╔══██║██║██╔══██╗██║   ██║  ╚██╔╝  ██╔══██║██║╚██╗██║██╔══╝  ██╔═██╗ ██║   ██║
 ███████║██║  ██║██║██████╔╝╚██████╔╝   ██║   ██║  ██║██║ ╚████║███████╗██║  ██╗╚██████╔╝
 ╚══════╝╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝
[/#27d16f]
"""

NEKO_LOGO = r"""
 /\__/\    ♥
( o . - ) /
---.----.
"""



def _detect_config() -> Config:
    explicit_provider = os.environ.get("NEKO_PROVIDER", "").strip().lower()
    if explicit_provider:
        if explicit_provider == "diy":
            diy_key = (
                os.environ.get("DIY_API_KEY", "")
                or os.environ.get("DIY_API", "")
                or os.environ.get("DIYAPI_KEY", "")
                or os.environ.get("DIYAPI", "")
            )
            diy_base_url = (
                os.environ.get("DIY_BASE_URL", "")
                or os.environ.get("DIY_URL", "")
                or os.environ.get("DIYBASEURL", "")
                or os.environ.get("DIYURL", "")
            )
            return Config(
                provider="diy",
                api_key=diy_key,
                base_url=diy_base_url or None,
                model=os.environ.get("DIY_MODEL", "").strip() or None,
            )

        preset = PROVIDER_PRESETS.get(explicit_provider)
        if preset:
            return Config(
                provider=explicit_provider,
                api_key=os.environ.get(preset["env_key"], ""),
                base_url=preset.get("base_url") or None,
                model=os.environ.get("MODEL", "").strip() or None,
            )

    priority = ["diy", "anthropic", "minimax", "openai", "gemini", "kimi", "deepseek", "qwen"]
    for name in priority:
        preset = PROVIDER_PRESETS[name]
        env_key = preset["env_key"]
        key = os.environ.get(env_key, "")
        if not key and name == "diy":
            key = (
                os.environ.get("DIY_API", "")
                or os.environ.get("DIYAPI", "")
                or os.environ.get("DIYAPI_KEY", "")
            )
        if not key:
            continue

        base_url = preset.get("base_url") or None
        model = None
        if name == "diy":
            base_url = (
                os.environ.get("DIY_BASE_URL")
                or os.environ.get("DIY_URL")
                or os.environ.get("DIYBASEURL")
                or os.environ.get("DIYURL")
                or base_url
            )
            if not base_url:
                continue
            model = os.environ.get("DIY_MODEL", "").strip() or None

        return Config(provider=name, api_key=key, base_url=base_url, model=model)

    console.print("[red]No API key found.[/red]\n")
    table = Table(title="Supported Providers", show_lines=True)
    table.add_column("Provider", style=BRAND_GREEN)
    table.add_column("Env Variable", style="yellow")
    table.add_column("Default Model", style=BRAND_GREEN)
    for name in priority:
        p = PROVIDER_PRESETS[name]
        table.add_row(name, p["env_key"], p["model"])
    console.print(table)
    console.print("\n[dim]Set one of the above env vars and try again.[/dim]")
    sys.exit(1)


async def repl():
    config = _detect_config()

    memory = None
    if config.feature("MEMORY"):
        memory = Memory(config.effective_memory_dir)
        memory_prompt = memory.build_prompt()
        config.append_system_prompt = memory_prompt

    mcp_manager = None
    if config.feature("MCP") and config.mcp_servers:
        mcp_manager = MCPManager()
        servers = [MCPServerConfig(**s) for s in config.mcp_servers]
        await mcp_manager.connect_all(servers)

    event_queue = asyncio.Queue[str]() if config.feature("COORDINATOR") else None
    local_tools = get_default_tools()
    if config.feature("COORDINATOR") and event_queue is not None:
        from neko_agent.agents.coordinator import Coordinator
        local_tools = [
            *local_tools,
            *Coordinator.get_coordinator_tools(config, local_tools, event_queue),
        ]

    engine = Engine(
        config=config,
        tools=local_tools,
        event_queue=event_queue,
        memory=memory,
    )

    mcp_tools = []
    if mcp_manager:
        mcp_tools = await mcp_manager.discover_tools_async(engine.registry)

    local_tool_count = len(local_tools)
    mcp_tool_count = len(mcp_tools)
    memory_status = (
        f"Memory: {config.effective_memory_dir}"
        if config.feature("MEMORY")
        else "Memory: disabled"
    )

    banner_content = (
        f"{SHIBUYA_NEKO_LOGO}\n"
        f"[{BRAND_GREEN}]{NEKO_LOGO}[/]\n"
        f"[bold {BRAND_GREEN}]Neko Agent[/bold {BRAND_GREEN}]\n"
        f"[dim]Vendor: [bold]{config.provider}[/bold] | "
        f"Model: [bold]{config.effective_model}[/bold] | "
        f"Local Tools: {local_tool_count} | "
        f"MCP: {len(config.mcp_servers) if config.mcp_servers else 0} | "
        f"MCP Tools: {mcp_tool_count}[/dim]\n"
        f"[dim]{memory_status}[/dim]"
    )
    console.print(Panel.fit(
        banner_content,
        border_style=BRAND_GREEN,
        padding=(1, 2),
        box=box.ROUNDED,
        subtitle="Neko v1.0",
    ))
    help_line = Text("Neko choose：", style="dim")
    help_line.append("/quit", style=BRAND_GREEN)
    help_line.append(" to exit, ", style="dim")
    help_line.append("/tools", style=BRAND_GREEN)
    help_line.append(" to list, ", style="dim")
    help_line.append("/reset", style=BRAND_GREEN)
    help_line.append(" to clear.", style="dim")
    console.print(help_line, highlight=False)
    console.print()

    try:
        while True:
            try:
                user_input = console.input(USER_PROMPT)
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input.strip():
                continue

            if user_input.strip() == "/quit":
                break
            if user_input.strip() == "/reset":
                engine.reset()
                console.print("[dim]Conversation reset.[/dim]")
                continue
            if user_input.strip() == "/tools":
                console.print(f"[bold {BRAND_GREEN}]Local Tools[/bold {BRAND_GREEN}]")
                for t in local_tools:
                    console.print(f"  [cyan]{t.name}[/cyan] — {t.description[:60]}")
                if mcp_tools:
                    console.print(f"\n[bold {BRAND_GREEN}]MCP Tools[/bold {BRAND_GREEN}]")
                    for t in mcp_tools:
                        console.print(f"  [yellow]{t.name}[/yellow] — {t.description[:60]}")
                continue
            if user_input.strip() == "/provider":
                console.print(f"  Provider: [cyan]{config.provider}[/cyan]")
                console.print(f"  Model: [cyan]{config.effective_model}[/cyan]")
                continue

            async for event in engine.run(user_input):
                if event["type"] == "thinking":
                    console.print(f"  [dim italic] {_truncate(event['content'], 100)}[/dim italic]")
                elif event["type"] == "tool_call":
                    tool_name = event["name"]
                    if tool_name.startswith("mcp__"):
                        console.print(f"  [yellow]{tool_name}[/yellow]")
                    else:
                        console.print(
                            f"  [yellow] {tool_name}[/yellow]"
                            f"[dim]({_truncate(str(event['arguments']), 80)})[/dim]"
                        )
                elif event["type"] == "tool_result":
                    if not event["name"].startswith("mcp__"):
                        output = _truncate(event["content"], 200)
                        console.print(f"  [dim]→ {output}[/dim]")
                elif event["type"] == "done":
                    console.print()
                    console.print(ASSISTANT_PROMPT, end="")
                    console.print(Markdown(event["content"]))
                    console.print()
                elif event["type"] == "error":
                    console.print(f"[red]Error: {event['content']}[/red]")

    finally:
        if mcp_manager:
            await mcp_manager.close()
        console.print("\n[dim]Bye![/dim]")


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


def main():
    asyncio.run(repl())


if __name__ == "__main__":
    main()
