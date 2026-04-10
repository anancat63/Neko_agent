"""工具权限策略与危险操作检测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Any, Optional

from neko_agent.core.tool import Tool, RiskLevel, PermissionCheck


class PermissionMode(str, Enum):
    DEFAULT = "default"
    AUTO = "auto"
    BYPASS = "bypass"


SYSTEM_DESTRUCTIVE = {
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "halt",
    "> /dev/sda",
    "format c:",
    "del /f /s /q c:",
}

GIT_DESTRUCTIVE_PATTERNS = [
    r"git\s+push\s+.*--force",
    r"git\s+push\s+-f\b",
    r"git\s+reset\s+--hard",
    r"git\s+checkout\s+\.",
    r"git\s+restore\s+\.",
    r"git\s+clean\s+-f",
    r"git\s+branch\s+-D",
    r"git\s+.*--no-verify",
    r"git\s+.*--no-gpg-sign",
    r"git\s+config\b",
]

PACKAGE_DANGEROUS = [
    r"pip\s+install\s+--break-system-packages",
    r"npm\s+publish",
    r"npm\s+unpublish",
    r"yarn\s+publish",
]

INFRA_DANGEROUS = [
    r"docker\s+rm\s+-f",
    r"docker\s+system\s+prune",
    r"kubectl\s+delete",
    r"terraform\s+destroy",
]

EXFIL_PATTERNS = [
    r"curl\s+.*\|\s*bash",
    r"wget\s+.*\|\s*bash",
    r"curl\s+.*\|\s*sh",
    r"wget\s+.*\|\s*sh",
]

_DANGEROUS_REGEXES = [
    re.compile(p, re.IGNORECASE)
    for p in (GIT_DESTRUCTIVE_PATTERNS + PACKAGE_DANGEROUS + INFRA_DANGEROUS + EXFIL_PATTERNS)
]


PROTECTED_PATHS = {
    ".bashrc", ".zshrc", ".bash_profile", ".profile",
    ".gitconfig", ".ssh/", ".gnupg/",
    ".env", ".env.local", ".env.production",
    ".mcp.json",
    "credentials.json", "service-account.json",
}


@dataclass
class PermissionContext:
    mode: PermissionMode = PermissionMode.DEFAULT
    allow_rules: dict[str, list[str]] = field(default_factory=dict)
    deny_rules: dict[str, list[str]] = field(default_factory=dict)
    denial_count: int = 0


def check_permission(
    tool: Tool,
    arguments: dict[str, Any],
    context: PermissionContext,
) -> PermissionCheck:
    if tool.name in context.deny_rules:
        return PermissionCheck(allowed=False, reason=f"Tool '{tool.name}' is denied by policy")

    if tool.name in context.allow_rules:
        return PermissionCheck(allowed=True)

    if context.mode == PermissionMode.BYPASS:
        return PermissionCheck(allowed=True)

    if context.mode == PermissionMode.AUTO:
        if tool.is_read_only:
            return PermissionCheck(allowed=True)
        if tool.risk_level == RiskLevel.LOW:
            return PermissionCheck(allowed=True)
        return PermissionCheck(allowed=False, reason="Auto mode: requires approval for non-read operations")

    return tool.check_permissions(arguments, context)


def is_dangerous_command(command: str) -> bool:
    cmd_lower = command.strip().lower()

    for pattern in SYSTEM_DESTRUCTIVE:
        if pattern in cmd_lower:
            return True

    for regex in _DANGEROUS_REGEXES:
        if regex.search(command):
            return True

    return False


def is_protected_file(path: str) -> bool:
    basename = os.path.basename(path)
    for protected in PROTECTED_PATHS:
        if protected.endswith("/"):
            if f"/{protected}" in path or path.startswith(protected):
                return True
        elif basename == protected:
            return True
    return False
