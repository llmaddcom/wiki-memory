"""source 路由：经历材料的 ingest 与读取（不可变，无更新/删除）。

输入内容规范见 docs/contract.md（各 kind 的正文格式与 salience 建议）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...db import get_session
from ...models import Source, SourceStatus, Space
from ...repositories import source_repo
from .. import schemas
from ..deps import get_space, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/spaces/{space_uid}/sources", response_model=Source)
def ingest_source(
    payload: schemas.SourceIngest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    return source_repo.add(
        session,
        space_id=space.id,
        kind=payload.kind,
        content=payload.content,
        external_ref=payload.external_ref,
        salience=payload.salience,
        occurred_at=payload.occurred_at,
    )


@router.get("/spaces/{space_uid}/sources", response_model=list[Source])
def list_sources(
    status: Optional[SourceStatus] = None,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    return source_repo.list_by_space(session, space.id, status=status)


@router.get("/spaces/{space_uid}/sources/{source_id}", response_model=Source)
def read_source(
    source_id: int,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    source = source_repo.get(session, space.id, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source
