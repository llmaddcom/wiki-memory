"""API 出入参 DTO：对外契约的形状定义（详见 docs/contract.md）。

对外不透传任何内部实现细节；召回响应中的 context_block 是
可直接注入 LLM 对话的标准文本块。
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..models import PageType, SourceKind


class SpaceCreate(BaseModel):
    """三种用法：传 uid（跨系统对齐、幂等）；传 owner_id+subject_id（按标签
    幂等 get-or-create）；全不传（服务生成新 uid）。"""

    uid: Optional[str] = Field(default=None, min_length=8, max_length=64)
    owner_id: Optional[str] = None
    subject_id: Optional[str] = None


class SourceIngest(BaseModel):
    kind: SourceKind
    content: str = Field(min_length=1)
    occurred_at: Optional[datetime] = None
    external_ref: Optional[dict] = None
    salience: float = Field(default=0.0, ge=0.0, le=1.0)


class IndexEntry(BaseModel):
    type: PageType
    slug: str
    title: str
    summary: str
    updated_at: datetime


class RollbackRequest(BaseModel):
    seq: int


class ConsolidateRequest(BaseModel):
    trigger: str = "manual"
    max_sources: Optional[int] = Field(default=None, ge=1, le=200)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    method: Literal["fuzzy", "bm25", "llm"] = "bm25"
    max_pages: int = Field(default=3, ge=1, le=10)


class RecallHitOut(BaseModel):
    slug: str
    title: str
    type: PageType
    summary: str
    score: Optional[float] = None
    body: str
    updated_at: datetime


class RecallResponse(BaseModel):
    method: str
    hits: list[RecallHitOut]
    context_block: str  # 直接注入 LLM 对话的 <recalled_memory> 文本块
    prompt_tokens: int = 0
    completion_tokens: int = 0
