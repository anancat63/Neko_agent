"""
工具集合入口。
统一组装内置工具实例，保留原有能力，仅切换到新的类名和文件名。
"""
from neko_agent.tools.content_scan_tool import ContentScanTool
from neko_agent.tools.live_search_tool import LiveSearchTool
from neko_agent.tools.page_fetch_tool import PageFetchTool
from neko_agent.tools.path_glob_tool import PathPatternTool
from neko_agent.tools.shell_exec_tool import ShellExecTool
from neko_agent.tools.workspace_file_tools import FilePatchTool, FilePeekTool, FileSaveTool


def get_default_tools():
    """返回默认启用的内置工具列表。"""
    return [
        ShellExecTool(),
        FilePeekTool(),
        FileSaveTool(),
        FilePatchTool(),
        PathPatternTool(),
        ContentScanTool(),
        PageFetchTool(),
        LiveSearchTool(),
    ]
