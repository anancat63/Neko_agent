"""运行配置（Provider/模型参数/功能开关/权限策略等）。"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _default_cwd() -> str:
    env_cwd = os.environ.get("NEKO_AGENT_CWD", "").strip()
    if env_cwd:
        return env_cwd
    try:
        return os.getcwd()
    except Exception:
        return str(Path(__file__).resolve().parent.parent)


@dataclass
class Config:
    provider: str = "anthropic"
    api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    base_url: Optional[str] = None
    model: Optional[str] = None

    max_turns: int = 50
    max_tokens: int = 4096
    temperature: float = 1.0
    cwd: str = field(default_factory=_default_cwd)

    permission_mode: str = "default"

    memory_dir: Optional[str] = None

    features: dict = field(default_factory=lambda: {
        "MEMORY": True,
        "DREAM": True,
        "COORDINATOR": False,
        "MCP": True,
        "SUB_AGENT": True,
    })

    mcp_servers: list = field(default_factory=lambda: [
        {
            "name": "github",
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-github",
            ],
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", ""),
            },
        }
    ] if os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") else [])

    system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None

    def feature(self, name: str) -> bool:
        return self.features.get(name, False)

    @property
    def effective_memory_dir(self) -> str:
        if self.memory_dir:
            return self.memory_dir
        return os.path.join(self.cwd, "memory_db")

    @property
    def effective_model(self) -> str:
        if self.model:
            return self.model
        if self.provider.lower() == "diy":
            diy_model = os.environ.get("DIY_MODEL", "").strip()
            if diy_model:
                return diy_model
        from neko_agent.core.provider import PROVIDER_PRESETS
        preset = PROVIDER_PRESETS.get(self.provider.lower(), {})
        return preset.get("model", "gpt-4o")

    @property
    def effective_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from neko_agent.core.provider import PROVIDER_PRESETS
        preset = PROVIDER_PRESETS.get(self.provider.lower(), {})
        env_key = preset.get("env_key", "")
        if env_key:
            value = os.environ.get(env_key, "")
            if value:
                return value
        if self.provider.lower() == "diy":
            return (
                os.environ.get("DIY_API", "")
                or os.environ.get("DIYAPI", "")
                or os.environ.get("DIYAPI_KEY", "")
            )
        return ""
