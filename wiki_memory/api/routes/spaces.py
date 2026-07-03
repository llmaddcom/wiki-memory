"""space 路由：记忆库的创建（幂等）、列举与读取。

对外身份是 uid；owner_id 仅作分组标签用于列举/预览（记忆预览场景：
GET /spaces?owner_id=xxx 拿到某用户全部记忆库）。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...db import get_session
from ...models import Space
from ...repositories import space_repo
from .. import schemas
from ..deps import get_space, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/spaces", response_model=Space)
def create_space(payload: schemas.SpaceCreate, session: Session = Depends(get_session)):
    return space_repo.get_or_create(
        session,
        uid=payload.uid,
        owner_id=payload.owner_id,
        subject_id=payload.subject_id,
    )


@router.get("/spaces", response_model=list[Space])
def list_spaces(owner_id: Optional[str] = None, session: Session = Depends(get_session)):
    return space_repo.list_spaces(session, owner_id=owner_id)


@router.get("/spaces/{space_uid}", response_model=Space)
def read_space(space: Space = Depends(get_space)):
    return space


@router.delete("/spaces/{space_uid}")
def delete_space(
    space: Space = Depends(get_space), session: Session = Depends(get_session)
):
    """整库删除该 space（上游删除数字人等场景），级联清空全部行，不可恢复。"""
    return space_repo.delete_space(session, space)
