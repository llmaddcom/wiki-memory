"""模糊匹配召回：加权词频，标题×3 / 摘要×2 / 正文×1。

最朴素也最快的一档：查询分词后统计各词在页面各字段的出现次数
加权求和，分数为零的页面不返回。适合"关键词能对上"的场景。
"""

from collections import Counter

from ..models import Page
from .base import RecallHit, RecallOutcome
from .tokenize import tokenize

_FIELD_WEIGHTS = (("title", 3.0), ("summary", 2.0), ("body", 1.0))


class FuzzyRecall:
    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome:
        terms = set(tokenize(query))
        if not terms:
            return RecallOutcome()
        scored: list[RecallHit] = []
        for page in pages:
            score = 0.0
            for field_name, weight in _FIELD_WEIGHTS:
                counts = Counter(tokenize(getattr(page, field_name)))
                score += weight * sum(counts[t] for t in terms)
            if score > 0:
                scored.append(RecallHit(page=page, score=score))
        scored.sort(key=lambda h: h.score, reverse=True)
        return RecallOutcome(hits=scored[:max_pages])
