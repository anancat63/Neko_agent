# Neko Agent（渋谷ねこ）— Provider-agnostic Python 编程助手 / 智能体框架

Neko Agent 是一个以 CLI 交互为核心的 Python 智能体框架：在任意目录启动，即可让模型以“工具调用”的方式读取/搜索/修改当前目录内的文件，并支持多厂商大模型（OpenAI 兼容、Claude、Gemini 等）以及 MCP 外接工具生态。

本项目的目标是把“闭源命令行编程助手”的体验，用可读、可扩展、可二次开发的 Python 代码完整复刻出来：你可以直接当成一个可用的 CLI，也可以把它当作底座嵌入你自己的垂直智能体。

---

## 项目构造

```
neko_agent/
  neko_agent/
    __main__.py            # CLI 入口（REPL），可用 `python -m neko_agent` 或 `agent`
    config.py              # 统一配置（cwd/feature flags/模型参数/权限策略等）
    core/
      engine.py            # 核心 Agent 循环（消息、工具调用、重试、压缩、事件回流）
      prompts.py           # PromptBuilder：底座规则 + 输出风格 + 业务注入 + 记忆注入
      provider.py          # Provider 抽象层（OpenAI-compatible / Anthropic / Gemini / DIY）
      permissions.py       # 工具权限与风险等级
      compact.py           # Auto-Compact：上下文逼近上限时自动摘要压缩
      mcp_client.py        # MCP 客户端：连接外部 server 并动态注册工具
      tool.py              # Tool/ToolRegistry/ToolContext 等基础抽象
      messages.py          # 统一消息结构与 API 格式转换
    tools/
      shell_exec_tool.py   # 运行 shell 命令（有权限控制）
      workspace_file_tools.py  # 文件读取/写入/精确替换
      path_glob_tool.py    # 路径模式匹配（glob）
      content_scan_tool.py # 内容扫描（文件级检索）
      live_search_tool.py  # 辅助搜索
      page_fetch_tool.py   # 页面抓取（用于联网信息）
  memory_db/               # 记忆落盘目录（SQLite）
  pyproject.toml           # Python 包定义 + 依赖 + CLI scripts
  .env.example             # 环境变量示例
  readme_cn.md
```

---

## 具体实现（核心设计）

### 1) “在哪启动，就在哪工作”的目录语义

CLI 启动时会把 `cwd` 设为进程当前目录（支持通过 `NEKO_AGENT_CWD` 强制覆盖）。工具读写文件、glob/scan 等操作都以 `cwd` 为根目录解析相对路径，因此你可以在任意项目目录里直接启动，让助手“就地干活”。

### 2) Engine：可流式的工具调用循环

[engine.py](./neko_agent/core/engine.py) 是系统中枢，负责：

- 组装系统提示词（PromptBuilder + 业务注入 + 记忆注入）
- 维护对话消息列表，并转换为上游 API 的请求格式
- 从模型输出中解析工具调用（tool_calls），按权限策略执行工具
- 处理 API 重试（429/5xx/超时等）
- 在上下文逼近上限时触发 Auto-Compact 压缩对话
- 可选：接收 Coordinator 的事件回流（异步子任务结果注入主对话）

### 3) Provider 抽象层：同一套 Agent 流跑多家模型

[provider.py](./neko_agent/core/provider.py) 统一了不同厂商 API 的差异，Engine 只依赖一个接口：`LLMProvider.chat()`。

- OpenAI-compatible：覆盖 OpenAI / MiniMax / Kimi / DeepSeek / Qwen / 以及任意兼容 OpenAI 的自定义网关
- Anthropic：使用官方 SDK，处理 tool_use / tool_result 的内容块格式
- Gemini：使用 google-genai SDK，进行工具调用适配
- DIY：支持自定义 base_url，并可通过模型名或环境变量自动推断 OpenAI/Anthropic 协议

### 4) Tools：可控的“读写 + 搜索 + 执行”能力集

[tools](./neko_agent/tools) 目录内置了一组面向“编程助手”场景的工具，包含：

- 文件读取/覆盖写入/精确字符串替换
- 文件路径模式匹配（glob）
- 目录内容扫描/搜索
- shell 命令执行（配合权限策略）

工具都会通过 `RiskLevel` 与权限策略进行约束，避免危险操作默认自动执行。

### 5) Memory：可检索的长期记忆（SQLite）

默认启用 `MEMORY` 特性时，系统会把记忆落到 `cwd/memory_db`（可通过 `memory_dir` 覆盖），并在每次提问前检索相关记忆片段注入上下文，让助手长期运行时更“懂你”。

### 6) MCP：外接工具生态（可选）

启用 `MCP` 后，可以连接外部 MCP Server（例如 GitHub、filesystem 等），将外部能力动态注册为工具，让 Agent 扩展到更广的生态。

---

## 技术栈

- Python：>= 3.11（见 [pyproject.toml](./pyproject.toml)）
- 依赖管理：PEP 621 / pyproject.toml
- 终端交互：rich
- 网络请求：httpx
- 配置：python-dotenv
- 数据校验：pydantic
- 模型接入：openai SDK（兼容层），可选 anthropic / google-genai
- 协议扩展：MCP（Model Context Protocol，部分 MCP Server 需要 Node.js/npx）

---

## 快速上手（Windows / CMD）

下面分两步：先用 venv 本地验证 OK；再安装到系统 base 环境，以后在任何目录直接 `agent` 启动。

### 1) 用 venv 本地测试

```powershell
git clone https://github.com/<yourname>/Shibuyaneko_agent.git
cd Shibuyaneko_agent\neko_agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -e .
```

可选安装：

```powershell
# 安装全部 Provider（额外包含 Claude/Gemini 官方 SDK）
pip install -e ".[all]"

# 开发依赖（pytest 等）
pip install -e ".[dev]"
```

设置环境变量（二选一：写到当前目录的 `.env`，或直接在终端里 set）。

推荐：在你准备让助手工作的项目目录创建 `.env`（CLI 会优先读取启动目录下的 `.env`）：

```env
# 任选其一：设置 NEKO_PROVIDER 显式指定（也可以不设，系统会按 key 自动识别）
NEKO_PROVIDER=minimax

# 对应 Provider 的 key（二选一即可）
MINIMAX_API_KEY=xxxx
# 或 OPENAI_API_KEY=xxxx
# 或 ANTHROPIC_API_KEY=xxxx
# 或 GEMINI_API_KEY=xxxx

# 可选：覆盖模型
# MODEL=gpt-4o
```

启动交互式编程助手：

```powershell
python -m neko_agent
```

### 2) 安装到系统 base 环境（以后可在任意目录启动）

退出 venv 后，在系统 Python（base）里进行可编辑安装：

```powershell
deactivate
pip install -e .
```

安装完成后，你可以在任意项目目录直接运行：

```powershell
agent
```

Neko Agent 会以“你启动命令时所在的路径”为工作目录读取/搜索/修改文件；如果你需要强制指定工作目录，可设置：

```powershell
setx NEKO_AGENT_CWD "D:\your\project"
```

---

## 常用环境变量速查

- 选择 Provider（可选）：`NEKO_PROVIDER`（diy / anthropic / minimax / openai / gemini / kimi / deepseek / qwen）
- API Key：
  - `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `MINIMAX_API_KEY` / `KIMI_API_KEY` / `DEEPSEEK_API_KEY` / `QWEN_API_KEY`
  - DIY：`DIY_API_KEY` + `DIY_BASE_URL`（可选 `DIY_MODEL` / `DIY_API_FORMAT`）
- 覆盖模型（可选）：`MODEL`
- 固定工作目录（可选）：`NEKO_AGENT_CWD`

---

## 二次开发

你可以把 Neko 当成框架引擎嵌入自己的程序：自定义 `Config.system_prompt` 注入垂直领域规则，或新增自定义 Tool 注册到 `ToolRegistry`，让助手具备你自己的业务能力。
