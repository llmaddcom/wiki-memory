"""keyword / page_keyword 表：关键字倒排通道（检索信号，纯派生物）。

固化时由 LLM 随页面操作生成 3~8 个可检索关键字（专名优先，禁高频泛化词），
落为 space 级词表 + 页级链接。召回时命中关键字的页面直达候选集并按
「指向页面数」降权加分——**只加分，不门控**（closets are a SIGNAL, never a GATE）。

派生物语义：损坏/升级可按 active 页全量重刷，不做增量修补；页面硬删与
REDACT 重固化时清除链接（被删材料可能是关键字的出处）。
"""

from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class Keyword(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("space_id", "term"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    space_id: int = Field(foreign_key="space.id", index=True)
    term: str = Field(index=True)


class PageKeyword(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("keyword_id", "page_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    keyword_id: int = Field(foreign_key="keyword.id", index=True)
    page_id: int = Field(foreign_key="page.id", index=True)
