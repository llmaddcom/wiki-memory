"""wiki 页面路由：索引 / 全文 / 按需展开 / 修订历史 / 出处链 / 回滚 / 软图谱。

页面内容只读；唯一的写操作是回滚（拷历史版为新版，历史不丢）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...db import get_session
from ...models import (
    Page,
    PageLink,
    PageRevision,
    PageStatus,
    PageType,
    RevisionTrigger,
    Space,
    utcnow,
)
from ...recall import render_context_block
from ...recall.base import RecallHit
from ...repositories import evidence_repo, link_repo, page_repo, revision_repo
from .. import schemas
from ..deps import get_space, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


def _get_page_or_404(session: Session, space: Space, slug: str) -> Page:
    page = page_repo.get_by_slug(session, space.id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page


@router.get("/spaces/{space_uid}/index", response_model=list[schemas.IndexEntry])
def read_index(space: Space = Depends(get_space), session: Session = Depends(get_session)):
    return [
        schemas.IndexEntry(
            type=p.type, slug=p.slug, title=p.title, summary=p.summary, updated_at=p.updated_at
        )
        for p in page_repo.list_active(session, space.id)
    ]


@router.get("/spaces/{space_uid}/pages", response_model=list[Page])
def list_pages(
    type: Optional[PageType] = None,
    status: PageStatus = PageStatus.active,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    return page_repo.list_pages(session, space.id, type=type, status=status)


@router.post(
    "/spaces/{space_uid}/pages/expand",
    response_model=schemas.ExpandResponse,
)
def expand_pages(
    payload: schemas.ExpandRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    """按 slug 批量展开 active 页全文，返回与 recall detail=full 同款可注入块。

    不存在或已归档的 slug 进 missing，不整单 404（模型可能点了悬空链）。
    """
    hits: list[schemas.RecallHitOut] = []
    recall_hits: list[RecallHit] = []
    missing: list[str] = []
    for slug in payload.slugs:
        page = page_repo.get_by_slug(session, space.id, slug)
        if page is None or page.status != PageStatus.active:
            missing.append(slug)
            continue
        hits.append(
            schemas.RecallHitOut(
                slug=page.slug,
                title=page.title,
                type=page.type,
                summary=page.summary,
                score=None,
                body=page.body,
                updated_at=page.updated_at,
            )
        )
        recall_hits.append(RecallHit(page=page))
    return schemas.ExpandResponse(
        hits=hits,
        missing=missing,
        context_block=render_context_block(recall_hits),
    )


@router.get("/spaces/{space_uid}/pages/{slug}", response_model=schemas.PageDetail)
def read_page(
    slug: str, space: Space = Depends(get_space), session: Session = Depends(get_session)
):
    page = _get_page_or_404(session, space, slug)
    # 全部修订关联 source 的发生日期，去重升序——联想工具据此翻对应日记
    dates = sorted(
        {f"{e['source_occurred_at']:%Y-%m-%d}" for e in evidence_repo.list_for_page(session, page.id)}
    )
    return schemas.PageDetail(**page.model_dump(), evidence_dates=dates)


@router.get("/spaces/{space_uid}/pages/{slug}/revisions", response_model=list[PageRevision])
def list_revisions(
    slug: str, space: Space = Depends(get_space), session: Session = Depends(get_session)
):
    page = _get_page_or_404(session, space, slug)
    return revision_repo.list_for_page(session, page.id)


@router.get("/spaces/{space_uid}/pages/{slug}/evidence")
def list_evidence(
    slug: str, space: Space = Depends(get_space), session: Session = Depends(get_session)
):
    page = _get_page_or_404(session, space, slug)
    return evidence_repo.list_for_page(session, page.id)


@router.post("/spaces/{space_uid}/pages/{slug}/rollback", response_model=Page)
def rollback_page(
    slug: str,
    payload: schemas.RollbackRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    page = _get_page_or_404(session, space, slug)
    target = revision_repo.get_by_seq(session, page.id, payload.seq)
    if target is None:
        raise HTTPException(status_code=404, detail=f"revision seq={payload.seq} not found")
    page.title = target.title
    page.hook = target.hook
    page.happened_on = target.happened_on
    page.summary = target.summary
    page.body = target.body
    page.status = PageStatus.active
    page.updated_at = utcnow()
    revision_repo.add(
        session, page, f"回滚到第 {payload.seq} 版", RevisionTrigger.rollback
    )
    session.commit()
    session.refresh(page)
    return page


@router.post("/spaces/{space_uid}/pages/{slug}/archive", response_model=Page)
def archive_page(
    slug: str,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    """人工归档（用户明确要求"忘掉"）：页面退出索引与召回，历史与出处保留可审计。"""
    page = _get_page_or_404(session, space, slug)
    if page.status == PageStatus.archived:
        return page
    page.status = PageStatus.archived
    page.updated_at = utcnow()
    revision_repo.add(session, page, "人工归档（用户要求遗忘）", RevisionTrigger.manual)
    session.commit()
    session.refresh(page)
    return page


@router.get("/spaces/{space_uid}/links", response_model=list[PageLink])
def list_links(
    dangling: Optional[bool] = None,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
):
    return link_repo.list_by_space(session, space.id, dangling=dangling)
