"""page_embedding 表：语义召回通道的页级向量（纯派生物）。

每页一条短向量（只 embed hook+summary——高密度检索面，正文细节靠 evidence
下钻）。向量以 JSON 数组落库、内存算余弦：页面规模数百内毫秒级，且 SQLite/
Postgres 双方言零依赖；规模大到吃紧再评估 pgvector。

embedder 身份校验：``model_tag``/``dim`` 随行落库，召回时与当前配置不符的行
视为失效、按需重算（惰性重刷，NORMALIZE_VERSION 模式）。固化改写、REDACT、
回滚等写点只做**失效**（删行），不在写路径上同步调用 embedder。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel, UniqueConstraint

from .base import utcnow


class PageEmbedding(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("page_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    page_id: int = Field(foreign_key="page.id", index=True)
    space_id: int = Field(foreign_key="space.id", index=True)
    model_tag: str  # 生成该向量的 embedder 模型名（身份校验）
    dim: int  # 向量维度（身份校验第二道）
    vector: list[float] = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)
