"""space 仓储：记忆库的创建与查找。

身份规则：uid 是唯一身份；调用方传 uid 则按 uid 幂等 get-or-create，
不传 uid 但传 owner_id+subject_id 则按标签对幂等，全都不传则新建。
"""

from typing import Optional

from sqlmodel import Session, select

from ..models import Space


def get_by_uid(session: Session, uid: str) -> Optional[Space]:
    return session.exec(select(Space).where(Space.uid == uid)).first()


def get_or_create(
    session: Session,
    uid: Optional[str] = None,
    owner_id: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> Space:
    if uid:
        existing = get_by_uid(session, uid)
        if existing:
            return existing
    elif owner_id and subject_id:
        existing = session.exec(
            select(Space).where(
                Space.owner_id == owner_id, Space.subject_id == subject_id
            )
        ).first()
        if existing:
            return existing
    space = Space(owner_id=owner_id, subject_id=subject_id)
    if uid:
        space.uid = uid
    session.add(space)
    session.commit()
    session.refresh(space)
    return space


def list_spaces(session: Session, owner_id: Optional[str] = None) -> list[Space]:
    stmt = select(Space)
    if owner_id:
        stmt = stmt.where(Space.owner_id == owner_id)
    return list(session.exec(stmt.order_by(Space.created_at)).all())


def delete_space(session: Session, space: Space) -> dict:
    """整库删除某 space（数字人被删除等场景）：级联清掉其全部行，返回删除计数。

    这是记忆的"死亡"，不是遗忘——遗忘走固化的 archive；此操作不可恢复。
    """
    from ..models import ConsolidationRun, Evidence, Page, PageLink, PageRevision, Source

    pages = session.exec(select(Page).where(Page.space_id == space.id)).all()
    page_ids = [p.id for p in pages]
    revs = (
        session.exec(select(PageRevision).where(PageRevision.page_id.in_(page_ids))).all()
        if page_ids
        else []
    )
    rev_ids = [r.id for r in revs]
    counts = {"pages": len(pages), "revisions": len(revs), "sources": 0}
    if rev_ids:
        for ev in session.exec(select(Evidence).where(Evidence.revision_id.in_(rev_ids))).all():
            session.delete(ev)
    for link in session.exec(select(PageLink).where(PageLink.space_id == space.id)).all():
        session.delete(link)
    for r in revs:
        session.delete(r)
    for p in pages:
        session.delete(p)
    for s in session.exec(select(Source).where(Source.space_id == space.id)).all():
        counts["sources"] += 1
        session.delete(s)
    for run in session.exec(
        select(ConsolidationRun).where(ConsolidationRun.space_id == space.id)
    ).all():
        session.delete(run)
    session.delete(space)
    session.commit()
    return counts
