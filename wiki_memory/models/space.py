"""space 表：记忆隔离边界。

一个 space = 一份独立的记忆库（例如 某用户 × 某数字人）。
对外身份是 uid：调用方可自带 UUID（跨系统对齐），不传则服务生成；
owner_id / subject_id 是可选的业务标签，仅用于按用户分组列举与预览，
不参与身份判定。
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from .base import SCHEMA_VERSION, utcnow


def new_uid() -> str:
    return uuid.uuid4().hex


class Space(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    uid: str = Field(default_factory=new_uid, unique=True, index=True)
    owner_id: Optional[str] = Field(default=None, index=True)
    subject_id: Optional[str] = Field(default=None, index=True)
    schema_version: int = Field(default=SCHEMA_VERSION)
    created_at: datetime = Field(default_factory=utcnow)
