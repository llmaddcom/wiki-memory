"""召回策略包：多种召回方式实现同一契约，调用方按精度/速度取舍。

- fuzzy    ：模糊匹配（分词后加权词频，标题>摘要>正文），零依赖、毫秒级。
- bm25     ：经典 BM25 排序（内存计算，中文按二元组切分）+ 关键字倒排加分，毫秒级，默认。
- llm      ：LLM 读索引点名页面，语义最准但一次 LLM 往返，留给高价值场景。
- embedding：页级短向量（hook+summary）余弦排序，需配置 embedder 端点。
"""

from .base import RecallHit, RecallOutcome, RecallStrategy
from .bm25 import Bm25Recall
from .embedding import EmbeddingRecall
from .fuzzy import FuzzyRecall
from .llm import LlmRecall
from .render import render_context_block, render_hook_block, resolve_hook

METHODS = ("fuzzy", "bm25", "llm", "embedding")

__all__ = [
    "RecallHit",
    "RecallOutcome",
    "RecallStrategy",
    "FuzzyRecall",
    "Bm25Recall",
    "LlmRecall",
    "EmbeddingRecall",
    "render_context_block",
    "render_hook_block",
    "resolve_hook",
    "METHODS",
]
