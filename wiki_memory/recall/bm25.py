"""BM25 召回：经典概率排序，内存实时计算，无索引依赖。

每次查询对该 space 的 active 页面现算（页面规模数百内毫秒级），
文档 = 标题×3 + 摘要×2 + 正文 拼接的词袋，标准 k1/b 参数。
页面规模大到现算吃紧时，再考虑落索引或换向量。
"""

import math
from collections import Counter

from ..models import Page
from .base import RecallHit, RecallOutcome
from .tokenize import tokenize

_K1 = 1.5
_B = 0.75


def _doc_tokens(page: Page) -> list[str]:
    return (
        tokenize(page.title) * 3 + tokenize(page.summary) * 2 + tokenize(page.body)
    )


class Bm25Recall:
    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome:
        terms = tokenize(query)
        if not terms or not pages:
            return RecallOutcome()

        docs = [Counter(_doc_tokens(p)) for p in pages]
        doc_lens = [sum(c.values()) for c in docs]
        avg_len = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
        n = len(docs)

        df = Counter()
        for term in set(terms):
            df[term] = sum(1 for d in docs if term in d)

        scored: list[RecallHit] = []
        for page, doc, dl in zip(pages, docs, doc_lens):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf * (_K1 + 1) / (
                    tf + _K1 * (1 - _B + _B * dl / avg_len)
                )
            if score > 0:
                scored.append(RecallHit(page=page, score=round(score, 4)))
        scored.sort(key=lambda h: h.score, reverse=True)
        return RecallOutcome(hits=scored[:max_pages])
