"""page_link 仓储：软图谱边的重建、悬空愈合与列举。"""

from typing import Optional

from sqlmodel import Session, select

from ..models import Page, PageLink
from . import page_repo


def refresh_for_page(
    session: Session, space_id: int, page: Page, slugs: list[str]
) -> None:
    """按正文最新解析结果重建该页的出边；目标页不存在则留悬空。"""
    for link in session.exec(
        select(PageLink).where(PageLink.from_page_id == page.id)
    ).all():
        session.delete(link)
    for slug in slugs:
        target = page_repo.get_by_slug(session, space_id, slug)
        session.add(
            PageLink(
                space_id=space_id,
                from_page_id=page.id,
                to_slug=slug,
                to_page_id=target.id if target else None,
            )
        )


def resolve_dangling(session: Session, space_id: int) -> None:
    """悬空链接若目标页已存在（本次或历史建页）则接上——wiki 的自愈语义。"""
    dangling = session.exec(
        select(PageLink).where(
            PageLink.space_id == space_id, PageLink.to_page_id.is_(None)
        )
    ).all()
    for link in dangling:
        target = page_repo.get_by_slug(session, space_id, link.to_slug)
        if target:
            link.to_page_id = target.id
            session.add(link)


def list_by_space(
    session: Session, space_id: int, dangling: Optional[bool] = None
) -> list[PageLink]:
    stmt = select(PageLink).where(PageLink.space_id == space_id)
    if dangling is True:
        stmt = stmt.where(PageLink.to_page_id.is_(None))
    elif dangling is False:
        stmt = stmt.where(PageLink.to_page_id.is_not(None))
    return list(session.exec(stmt).all())
