"""consolidation_run 仓储：固化运行日志的创建、收尾、列举与互斥探测。"""

from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from ..models import ConsolidationRun, RunStatus, utcnow


def create(
    session: Session, space_id: int, trigger: str, source_ids: list[int]
) -> ConsolidationRun:
    run = ConsolidationRun(space_id=space_id, trigger=trigger, source_ids=source_ids)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish(
    session: Session,
    run: ConsolidationRun,
    status: RunStatus,
    pages_touched: Optional[list[str]] = None,
    error: Optional[str] = None,
) -> ConsolidationRun:
    run.status = status
    run.pages_touched = pages_touched
    run.error = error
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def find_active(
    session: Session, space_id: int, *, stale_seconds: int = 1800
) -> Optional[ConsolidationRun]:
    """该 space 是否有进行中的固化（互斥用）。running 超过 stale_seconds 视为死运行忽略。"""
    run = session.exec(
        select(ConsolidationRun)
        .where(
            ConsolidationRun.space_id == space_id,
            ConsolidationRun.status == RunStatus.running,
        )
        .order_by(ConsolidationRun.started_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return None
    if run.started_at < utcnow() - timedelta(seconds=stale_seconds):
        return None
    return run


def list_by_space(session: Session, space_id: int) -> list[ConsolidationRun]:
    return list(
        session.exec(
            select(ConsolidationRun)
            .where(ConsolidationRun.space_id == space_id)
            .order_by(ConsolidationRun.started_at.desc())
        ).all()
    )
