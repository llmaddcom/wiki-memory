"""source 路由：经历材料的 ingest、读取，与按上游出处的隐私删除。

内容不可更新；唯一的删除通路是 delete-by-ref（上游删除会话 → 连带
遗忘，见 docs/contract.md 与 deletion.py）。输入内容规范见
docs/contract.md（各 kind 的正文格式与 salience 建议）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ... import deletion
from ...db import get_session
from ...llm import ChatLLM
from ...models import Source, SourceStatus, Space
from ...repositories import source_repo
from .. import schemas
from ..deps import get_llm, get_space, require_api_key

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


@router.post(
    "/spaces/{space_uid}/sources/delete-by-ref/preview",
    response_model=schemas.DeleteBySourcePreview,
)
def preview_delete_by_ref(
    payload: schemas.DeleteBySourceRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    """dry-run：只算影响面不动库，供上游删除确认对话框展示。"""
    impact = deletion.assess(session, space.id, payload.external_ref)
    return schemas.DeleteBySourcePreview(
        matched_sources=len(impact.sources),
        matched_source_ids=sorted(impact.source_ids),
        pages_to_delete=[p.slug for p in impact.pages_to_delete],
        pages_to_reconsolidate=[p.slug for p in impact.pages_to_reconsolidate],
    )


@router.post(
    "/spaces/{space_uid}/sources/delete-by-ref",
    response_model=schemas.DeleteBySourceResult,
)
def delete_by_ref(
    payload: schemas.DeleteBySourceRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
    llm: ChatLLM = Depends(get_llm),
):
    """按 external_ref 硬删 source 并回收证据（隐私删除，不可恢复）。

    重固化失败时整体回退（未做任何删除），返回 502，上游可重试。
    """
    try:
        return deletion.execute(session, space, payload.external_ref, llm)
    except deletion.RedactionError as e:
        raise HTTPException(
            status_code=502, detail=f"重固化失败，未执行任何删除，可重试：{e}"
        )


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
