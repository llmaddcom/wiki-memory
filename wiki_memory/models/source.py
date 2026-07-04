"""source 表：经历材料的全文快照（海马体输入）。

内容只增不改（content + content_hash 快照进库），但**可被连带删除**：
上游删除原文（如用户删除会话）时按 external_ref 匹配硬删对应 source，
并经证据链回收受影响页面（隐私删除语义，见 deletion.py 与
docs/contract.md）。external_ref 记录上游出处（系统名 + id 等），
它同时是删除时的匹配键。
salience 是写入方给的显著性信号（用户纠正 / 任务失败 / 被要求记住 → 调高），
固化时供 LLM 参考。status 构成固化的工作队列：
pending（待固化）→ consolidated（已产生页面变更）/ skipped（判定不值得长期保留）。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from .base import SCHEMA_VERSION, utcnow


class SourceKind(str, Enum):
    diary = "diary"            # 上游日记条目
    turn = "turn"              # 对话回合（用户问 + AI 答）
    correction = "correction"  # 用户明确纠正 / "记住这个"
    skill_run = "skill_run"    # 工具/技能执行经历
    document = "document"      # 外部文档
    manual = "manual"          # 人工投喂


class SourceStatus(str, Enum):
    pending = "pending"
    consolidated = "consolidated"
    skipped = "skipped"


class Source(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    space_id: int = Field(foreign_key="space.id", index=True)
    kind: SourceKind
    content: str = Field(sa_column=Column(Text, nullable=False))
    content_hash: str = Field(index=True)
    external_ref: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    salience: float = Field(default=0.0)
    status: SourceStatus = Field(default=SourceStatus.pending, index=True)
    occurred_at: datetime = Field(default_factory=utcnow)
    ingested_at: datetime = Field(default_factory=utcnow)
    schema_version: int = Field(default=SCHEMA_VERSION)
