"""BM25 召回：经典概率排序，内存实时计算，无索引依赖。

每次查询对该 space 的 active 页面现算（页面规模数百内毫秒级），
文档 = 标题×3 + 钩子×3 + 摘要×2 + 正文 拼接的词袋，标准 k1/b 参数。
hook 与 title 同权：≤20 字含专名的钩子是最高密度的检索面。
页面规模大到现算吃紧时，再考虑落索引或换向量。

分数做 sigmoid 归一化到 (0,1)：raw BM25 量纲随 query 长度 / 库规模漂移，
归一后多信号加和（关键字 boost 等）才有稳定地板。midpoint/steepness 按
query 的 term 数（CJK 二元组口径）分五档查表——初始值为经验预置，
待自家语料按 query 长度分桶采 P50/P90 重标定（steepness ≈ 4/(P90−P50)）。

平分 tie-break：happened_on 新者优先（缺失视为最旧沉底）。
"""

import math
from collections import Counter
from datetime import date

from ..models import Page
from .base import RecallHit, RecallOutcome
from .tokenize import tokenize

_K1 = 1.5
_B = 0.75

# (term 数上限, midpoint, steepness)：五档分级，CJK 二元组口径
# （10 字中文 query ≈ 9 个二元组，英文分档直接照搬会全落高档）。
_SIGMOID_TIERS: tuple[tuple[int, float, float], ...] = (
    (4, 3.0, 1.0),
    (8, 5.0, 0.7),
    (14, 8.0, 0.5),
    (24, 12.0, 0.35),
)
_SIGMOID_TAIL = (18.0, 0.25)  # >24 term

_DATE_FLOOR = date.min  # happened_on 缺失 → 视为最旧


def _doc_tokens(page: Page) -> list[str]:
    return (
        tokenize(page.title) * 3
        + tokenize(page.hook) * 3
        + tokenize(page.summary) * 2
        + tokenize(page.body)
    )


def _sigmoid_params(term_count: int) -> tuple[float, float]:
    for cap, midpoint, steepness in _SIGMOID_TIERS:
        if term_count <= cap:
            return midpoint, steepness
    return _SIGMOID_TAIL


def normalize_score(raw: float, term_count: int) -> float:
    """raw BM25 → (0,1)：1/(1+exp(-steepness·(raw-midpoint)))，按 term 数分档。"""
    midpoint, steepness = _sigmoid_params(term_count)
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (raw - midpoint)))
    except OverflowError:
        return 0.0 if raw < midpoint else 1.0


def raw_scores(pages: list[Page], query: str) -> list[tuple[Page, float]]:
    """全量 raw BM25 计分（不截断、不归一），供策略与关键字并集通道共用。"""
    terms = tokenize(query)
    if not terms or not pages:
        return []

    docs = [Counter(_doc_tokens(p)) for p in pages]
    doc_lens = [sum(c.values()) for c in docs]
    avg_len = sum(doc_lens) / len(doc_lens) if doc_lens else 0.0
    n = len(docs)

    df = Counter()
    for term in set(terms):
        df[term] = sum(1 for d in docs if term in d)

    scored: list[tuple[Page, float]] = []
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
            scored.append((page, score))
    return scored


def sort_hits(hits: list[RecallHit]) -> None:
    """就地排序：分数降序，平分按 happened_on 新者优先（缺失沉底视为最旧）。"""
    hits.sort(
        key=lambda h: (h.score or 0.0, h.page.happened_on or _DATE_FLOOR),
        reverse=True,
    )


class Bm25Recall:
    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome:
        term_count = len(tokenize(query))
        scored: list[RecallHit] = []
        for page, raw in raw_scores(pages, query):
            norm = normalize_score(raw, term_count)
            scored.append(
                RecallHit(
                    page=page,
                    score=round(norm, 4),
                    score_details={
                        "bm25_raw": round(raw, 4),
                        "bm25_norm": round(norm, 4),
                        "keyword_boost": 0.0,
                        "max_possible": 1.0,
                        "final": round(norm, 4),
                    },
                )
            )
        sort_hits(scored)
        return RecallOutcome(hits=scored[:max_pages])
