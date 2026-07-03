"""page_link 表：[[链接]] 解析出的软知识图谱边。

页面是节点、链接是边——甩掉重型知识图谱后联想结构的轻量替代。
to_page_id 为空 = 悬空链接：不是错误，是"值得建页"的信号（lint 用）；
目标页建立后由固化收尾的重解析自动愈合。
"""

from typing import Optional

from sqlmodel import Field, SQLModel


class PageLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    space_id: int = Field(foreign_key="space.id", index=True)
    from_page_id: int = Field(foreign_key="page.id", index=True)
    to_slug: str = Field(index=True)
    to_page_id: Optional[int] = Field(default=None, foreign_key="page.id")
