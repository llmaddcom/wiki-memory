"""召回策略包：多种召回方式实现同一契约，调用方按精度/速度取舍。

- fuzzy：模糊匹配（分词后加权词频，标题>摘要>正文），零依赖、毫秒级。
- bm25 ：经典 BM25 排序（内存计算，中文按二元组切分），毫秒级，默认。
- llm  ：LLM 读索引点名页面，最准但最慢，留给高价值场景。

向量检索是预留的下一档（页面规模超出关键词方法时再上）。
"""

from .base import RecallHit, RecallOutcome, RecallStrategy
from .bm25 import Bm25Recall
from .fuzzy import FuzzyRecall
from .llm import LlmRecall
from .render import render_context_block, render_hook_block, resolve_hook

METHODS = ("fuzzy", "bm25", "llm")

__all__ = [
    "RecallHit",
    "RecallOutcome",
    "RecallStrategy",
    "FuzzyRecall",
    "Bm25Recall",
    "LlmRecall",
    "render_context_block",
    "render_hook_block",
    "resolve_hook",
    "METHODS",
]
