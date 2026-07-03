"""evidence 表：出处链（修订 ↔ source 多对多）。

回答"凭什么这么认为"：每一版认识都指回其依据的 source，
也是从压缩认识下钻回原始材料的入口。
"""

from typing import Optional

from sqlmodel import Field, SQLModel


class Evidence(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    revision_id: int = Field(foreign_key="pagerevision.id", index=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    note: Optional[str] = Field(default=None)
