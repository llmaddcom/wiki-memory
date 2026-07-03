"""source 仓储：经历材料的 ingest 与读取。

source 不可变：只有新增与状态流转（pending → consolidated/skipped），
没有更新和删除内容的入口。
"""

import hashlib
from datetime import datetime
from typing import Iterable, Optional

from sqlmodel import Session, select

from ..models import Source, SourceKind, SourceStatus, utcnow


def add(
    session: Session,
    space_id: int,
    kind: SourceKind,
    content: str,
    external_ref: Optional[dict] = None,
    salience: float = 0.0,
    occurred_at: Optional[datetime] = None,
) -> Source:
    source = Source(
        space_id=space_id,
        kind=kind,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        external_ref=external_ref,
        salience=salience,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def get(session: Session, space_id: int, source_id: int) -> Optional[Source]:
    return session.exec(
        select(Source).where(Source.id == source_id, Source.space_id == space_id)
    ).first()


def list_by_space(
    session: Session, space_id: int, status: Optional[SourceStatus] = None
) -> list[Source]:
    stmt = select(Source).where(Source.space_id == space_id)
    if status:
        stmt = stmt.where(Source.status == status)
    return list(session.exec(stmt.order_by(Source.occurred_at)).all())


def list_pending(session: Session, space_id: int, limit: int) -> list[Source]:
    return list(
        session.exec(
            select(Source)
            .where(Source.space_id == space_id, Source.status == SourceStatus.pending)
            .order_by(Source.occurred_at)
            .limit(limit)
        ).all()
    )


def mark_consumed(session: Session, sources: Iterable[Source], consumed_ids: set[int]) -> None:
    """固化收尾：被操作引用的标 consolidated，其余标 skipped（遗忘是功能）。"""
    for s in sources:
        s.status = (
            SourceStatus.consolidated if s.id in consumed_ids else SourceStatus.skipped
        )
        session.add(s)
