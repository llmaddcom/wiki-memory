"""数据模型包：一张表一个文件，此处统一导出。

依赖关系（也是记忆的生命线）：
space（隔离边界）→ source（不可变经历）→ consolidationrun（睡眠固化）
→ page（当前认识）→ pagerevision（历史）← evidence（出处）；page ↔ pagelink（软图谱）。
"""

from .base import SCHEMA_VERSION, utcnow
from .consolidation_run import ConsolidationRun, RunStatus
from .evidence import Evidence
from .keyword import Keyword, PageKeyword
from .page import Page, PageStatus, PageType
from .page_embedding import PageEmbedding
from .page_link import PageLink
from .page_revision import PageRevision, RevisionTrigger
from .source import Source, SourceKind, SourceStatus
from .space import Space, new_uid

__all__ = [
    "SCHEMA_VERSION",
    "utcnow",
    "Space",
    "new_uid",
    "Source",
    "SourceKind",
    "SourceStatus",
    "Page",
    "PageType",
    "PageStatus",
    "PageRevision",
    "RevisionTrigger",
    "Evidence",
    "PageLink",
    "Keyword",
    "PageKeyword",
    "PageEmbedding",
    "ConsolidationRun",
    "RunStatus",
]
