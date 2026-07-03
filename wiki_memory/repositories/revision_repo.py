"""page_revision 仓储：修订历史的追加与读取。

add() 对页面当前字段做快照并自动取下一个 seq；历史只增不删。
"""

from typing import Optional

from sqlmodel import Session, select

from ..models import Page, PageRevision, RevisionTrigger


def list_for_page(session: Session, page_id: int) -> list[PageRevision]:
    return list(
        session.exec(
            select(PageRevision)
            .where(PageRevision.page_id == page_id)
            .order_by(PageRevision.seq)
        ).all()
    )


def get_by_seq(session: Session, page_id: int, seq: int) -> Optional[PageRevision]:
    return session.exec(
        select(PageRevision).where(
            PageRevision.page_id == page_id, PageRevision.seq == seq
        )
    ).first()


def add(
    session: Session,
    page: Page,
    change_reason: str,
    trigger: RevisionTrigger,
    run_id: Optional[int] = None,
) -> PageRevision:
    last = session.exec(
        select(PageRevision)
        .where(PageRevision.page_id == page.id)
        .order_by(PageRevision.seq.desc())
        .limit(1)
    ).first()
    rev = PageRevision(
        page_id=page.id,
        seq=(last.seq if last else 0) + 1,
        title=page.title,
        summary=page.summary,
        body=page.body,
        change_reason=change_reason,
        trigger=trigger,
        run_id=run_id,
    )
    session.add(rev)
    session.flush()
    return rev
