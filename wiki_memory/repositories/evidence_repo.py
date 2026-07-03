"""evidence 仓储：出处链的写入与按页汇总。"""

from typing import Iterable, Optional

from sqlmodel import Session, select

from ..models import Evidence, PageRevision, Source


def add_many(
    session: Session,
    revision_id: int,
    source_ids: Iterable[int],
    note: Optional[str] = None,
) -> None:
    for sid in source_ids:
        session.add(Evidence(revision_id=revision_id, source_id=sid, note=note))


def list_for_page(session: Session, page_id: int) -> list[dict]:
    """页面全部修订的出处：凭什么这么认为 + 下钻回 source 的入口。"""
    rows = session.exec(
        select(PageRevision, Evidence, Source)
        .where(PageRevision.page_id == page_id)
        .where(Evidence.revision_id == PageRevision.id)
        .where(Source.id == Evidence.source_id)
        .order_by(PageRevision.seq)
    ).all()
    return [
        {
            "revision_seq": rev.seq,
            "change_reason": rev.change_reason,
            "source_id": src.id,
            "source_kind": src.kind,
            "source_occurred_at": src.occurred_at,
            "note": ev.note,
        }
        for rev, ev, src in rows
    ]
