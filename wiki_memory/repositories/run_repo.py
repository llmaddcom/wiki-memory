"""consolidation_run 仓储：固化运行日志的创建、收尾与列举。"""

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


def list_by_space(session: Session, space_id: int) -> list[ConsolidationRun]:
    return list(
        session.exec(
            select(ConsolidationRun)
            .where(ConsolidationRun.space_id == space_id)
            .order_by(ConsolidationRun.started_at.desc())
        ).all()
    )
