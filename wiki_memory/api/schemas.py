"""API 出入参 DTO：对外契约的形状定义（详见 docs/contract.md）。

对外不透传任何内部实现细节；召回响应中的 context_block 是
可直接注入 LLM 对话的标准文本块。
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from ..models import PageStatus, PageType, SourceKind


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


class DeleteBySourceRequest(BaseModel):
    """按上游出处删除：external_ref 子集匹配。至少传一个键；上游应带上
    system（如 {"system": "createrole", "session_id": "…"}），避免误伤
    其他系统写入的同名 id。"""

    external_ref: dict

    @field_validator("external_ref")
    @classmethod
    def _non_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("external_ref 至少需要一个键（推荐 system + session_id）")
        return v


class DeleteBySourcePreview(BaseModel):
    """dry-run 影响面：供上游在删除确认对话框展示
    "将遗忘 N 条记忆、M 条因还有其他来源会保留"。"""

    matched_sources: int
    matched_source_ids: list[int]
    pages_to_delete: list[str]          # 唯一证据全来自被删 source → 将连历史删除
    pages_to_reconsolidate: list[str]   # 还有其他证据 → 剔证据 + 重固化，结论可能保留


class DeleteBySourceResult(BaseModel):
    """执行汇总（上游审计留痕）；run_id 关联本次删除的固化运行日志。"""

    deleted_sources: int
    deleted_pages: list[str]
    reconsolidated_pages: list[str]
    run_id: Optional[int] = None


class IndexEntry(BaseModel):
    type: PageType
    slug: str
    title: str
    summary: str
    updated_at: datetime


class PageDetail(BaseModel):
    """单页读取响应：Page 全字段 + evidence_dates（该页全部修订关联 source 的
    occurred_at 日期，YYYY-MM-DD 去重升序）——联想工具拿到日期即可去翻对应日记。"""

    id: int
    space_id: int
    type: PageType
    slug: str
    title: str
    hook: str
    happened_on: Optional[date] = None
    summary: str
    body: str
    attrs: Optional[dict] = None
    confidence: Optional[float] = None
    status: PageStatus
    schema_version: int
    created_at: datetime
    updated_at: datetime
    evidence_dates: list[str]


class RollbackRequest(BaseModel):
    seq: int


class ConsolidateRequest(BaseModel):
    trigger: str = "manual"
    max_sources: Optional[int] = Field(default=None, ge=1, le=200)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    method: Literal["fuzzy", "bm25", "llm"] = "bm25"
    max_pages: int = Field(default=3, ge=1, le=10)
    # hook=轻量钩子行（渐进披露：先注钩子，相关再展开），full=全文（默认，兼容旧调用方）
    detail: Literal["hook", "full"] = "full"


class RecallHitOut(BaseModel):
    slug: str
    title: str
    type: PageType
    summary: str
    score: Optional[float] = None
    body: str
    updated_at: datetime


class RecallHookHitOut(BaseModel):
    """detail="hook" 的轻量命中：只带钩子行所需字段，不含 body/summary。
    hook_fallback=true 表示存量页 hook 为空，降级用了 summary 前 20 字。"""

    slug: str
    title: str
    type: PageType
    hook: str
    happened_on: Optional[date] = None
    score: Optional[float] = None
    hook_fallback: bool = False


class RecallResponse(BaseModel):
    method: str
    hits: list[RecallHitOut] | list[RecallHookHitOut]
    context_block: str  # 直接注入 LLM 对话的 <recalled_memory> 文本块
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ExpandRequest(BaseModel):
    """按 slug 批量展开页面全文（渐进披露第二步）。"""

    slugs: list[str] = Field(min_length=1, max_length=10)


class ExpandResponse(BaseModel):
    """展开结果：命中页与 recall detail=full 同款可注入块；缺失/归档进 missing。"""

    hits: list[RecallHitOut]
    missing: list[str]
    context_block: str
