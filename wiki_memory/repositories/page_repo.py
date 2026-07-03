"""page 仓储：wiki 页面的查找与列举。

页面内容的改写只发生在固化引擎与回滚流程；这里不提供随意更新
正文的入口，保证"wiki 由固化过程维护"这一约束。
"""

from typing import Optional

from sqlmodel import Session, select

from ..models import Page, PageStatus, PageType


def get_by_slug(session: Session, space_id: int, slug: str) -> Optional[Page]:
    return session.exec(
        select(Page).where(Page.space_id == space_id, Page.slug == slug)
    ).first()


def list_active(session: Session, space_id: int) -> list[Page]:
    return list(
        session.exec(
            select(Page)
            .where(Page.space_id == space_id, Page.status == PageStatus.active)
            .order_by(Page.type, Page.slug)
        ).all()
    )


def list_pages(
    session: Session,
    space_id: int,
    type: Optional[PageType] = None,
    status: PageStatus = PageStatus.active,
) -> list[Page]:
    stmt = select(Page).where(Page.space_id == space_id, Page.status == status)
    if type:
        stmt = stmt.where(Page.type == type)
    return list(session.exec(stmt.order_by(Page.updated_at.desc())).all())
