"""LLM 召回：索引先行——LLM 读一行一页的索引，点名要展开的页面。

最准的一档（理解语义与言外之意），但一次 LLM 往返的延迟和费用，
留给高价值场景；解析失败抛 RecallError 由路由层转 502。
"""

from ..consolidation import prompts
from ..consolidation.engine import parse_json_object
from ..llm.base import ChatLLM, LLMError
from ..models import Page
from .base import RecallHit, RecallOutcome


class RecallError(Exception):
    pass


class LlmRecall:
    def __init__(self, llm: ChatLLM):
        self._llm = llm

    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome:
        if not pages:
            return RecallOutcome()
        try:
            res = self._llm.complete(
                prompts.RECALL_SYSTEM.format(max_pages=max_pages),
                f"## wiki 索引\n{prompts.render_index(pages)}\n\n## 当前情境\n{query}",
            )
            slugs = parse_json_object(res.text).get("slugs", [])[:max_pages]
        except (LLMError, ValueError) as e:
            raise RecallError(str(e)) from e
        by_slug = {p.slug: p for p in pages}
        hits = [RecallHit(page=by_slug[s]) for s in slugs if s in by_slug]
        return RecallOutcome(
            hits=hits,
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
        )
