"""page_revision 表：页面修订历史（可解释、可回滚、可审计）。

每次改写留一版，只增不删；回滚 = 把历史某版拷为新版（历史不丢）。
change_reason 一句话记录"为什么改"，trigger 记录改写来源
（固化 / 手动 / 回滚），run_id 关联触发本版的固化运行。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from .base import utcnow


class RevisionTrigger(str, Enum):
    consolidation = "consolidation"
    manual = "manual"
    rollback = "rollback"


class PageRevision(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("page_id", "seq"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    page_id: int = Field(foreign_key="page.id", index=True)
    seq: int
    title: str
    summary: str
    body: str = Field(sa_column=Column(Text, nullable=False))
    change_reason: str
    trigger: RevisionTrigger
    run_id: Optional[int] = Field(default=None, foreign_key="consolidationrun.id")
    created_at: datetime = Field(default_factory=utcnow)
