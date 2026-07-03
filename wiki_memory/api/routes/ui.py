"""记忆预览界面路由：/ui 返回单文件 Obsidian 风格浏览页。

预览是只读旁观（Karpathy："Obsidian 是 IDE，LLM 是程序员，wiki 是代码库"），
按 space uid 加载索引、页面、互链、修订、出处、来源与固化日志。
静态文件不鉴权；其内部 API 请求带用户填写的 X-API-Key。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_INDEX_HTML = Path(__file__).resolve().parent.parent.parent / "web" / "index.html"


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def ui() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")
