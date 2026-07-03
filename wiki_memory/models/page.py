"""page 表：wiki 页面的当前认识（皮层语义记忆）。

正文是 markdown（含 [[slug]] 互链），面向 LLM 消费；summary 是一行
高密度摘要，索引页由它拼出，召回先读索引再展开全文。
六种类型对应人类记忆分型（教训/大事记/人物/认识/经验/自我），
每型的正文分节模板见 consolidation/prompts.py。
页面只能经固化引擎或回滚改写，(space_id, slug) 唯一。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from .base import SCHEMA_VERSION, utcnow


class PageType(str, Enum):
    lesson = "lesson"        # 教训：犯过的错 + 为什么 + 下次怎么做
    event = "event"          # 大事记：有长期意义的情节
    person = "person"        # 人物画像：关系、偏好、禁忌、承诺
    belief = "belief"        # 认识/论点：结论 + 置信度 + 证据
    procedure = "procedure"  # 程序性经验：什么任务怎么做
    self = "self"            # 自我：persona 可变部分、成长状态


class PageStatus(str, Enum):
    active = "active"
    archived = "archived"


class Page(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("space_id", "slug"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    space_id: int = Field(foreign_key="space.id", index=True)
    type: PageType = Field(index=True)
    slug: str = Field(index=True)
    title: str
    summary: str
    body: str = Field(sa_column=Column(Text, nullable=False))
    attrs: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    confidence: Optional[float] = Field(default=None)  # belief 类使用
    status: PageStatus = Field(default=PageStatus.active, index=True)
    schema_version: int = Field(default=SCHEMA_VERSION)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
