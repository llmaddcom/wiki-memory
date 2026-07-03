"""固化路由：触发"睡眠"与查看运行日志。

上游想什么时候固化都行（日记生成后 / 会话结束 / cron），
本服务不内置调度。
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...config import settings
from ...consolidation.engine import ConsolidationEngine
from ...db import get_session
from ...models import ConsolidationRun, Space
from ...repositories import run_repo
from .. import schemas
from ..deps import get_engine, get_space, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/spaces/{space_uid}/consolidate", response_model=ConsolidationRun)
def consolidate(
    payload: schemas.ConsolidateRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
    engine: ConsolidationEngine = Depends(get_engine),
):
    return engine.run(
        session,
        space,
        trigger=payload.trigger,
        max_sources=payload.max_sources or settings.consolidate_max_sources,
    )


@router.get("/spaces/{space_uid}/runs", response_model=list[ConsolidationRun])
def list_runs(space: Space = Depends(get_space), session: Session = Depends(get_session)):
    return run_repo.list_by_space(session, space.id)
