"""召回路由：按选定策略检索页面，返回命中 + 可直接注入对话的 context_block。

method：fuzzy（模糊词频）/ bm25（默认，速度与质量的平衡）/ llm（最准最慢）。
detail：full（默认，页面全文）/ hook（轻量钩子行，渐进披露的逐回合注入）。
排序算法与 detail 无关（全字段计分），hook 只是响应裁剪。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...db import get_session
from ...llm import ChatLLM
from ...models import Space
from ...recall import render_context_block, render_hook_block, resolve_hook
from ...recall.llm import RecallError
from ...repositories import page_repo
from .. import schemas
from ..deps import build_recall_strategy, get_llm, get_space, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/spaces/{space_uid}/recall", response_model=schemas.RecallResponse)
def recall(
    payload: schemas.RecallRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
    llm: ChatLLM = Depends(get_llm),
):
    pages = page_repo.list_active(session, space.id)
    strategy = build_recall_strategy(payload.method, llm)
    try:
        outcome = strategy.retrieve(pages, payload.query, payload.max_pages)
    except RecallError as e:
        raise HTTPException(status_code=502, detail=f"recall LLM failed: {e}")
    if payload.detail == "hook":
        hook_hits = []
        for h in outcome.hits:
            hook, fallback = resolve_hook(h.page)
            hook_hits.append(
                schemas.RecallHookHitOut(
                    slug=h.page.slug,
                    title=h.page.title,
                    type=h.page.type,
                    hook=hook,
                    happened_on=h.page.happened_on,
                    score=h.score,
                    hook_fallback=fallback,
                )
            )
        return schemas.RecallResponse(
            method=payload.method,
            hits=hook_hits,
            context_block=render_hook_block(outcome.hits),
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
        )
    return schemas.RecallResponse(
        method=payload.method,
        hits=[
            schemas.RecallHitOut(
                slug=h.page.slug,
                title=h.page.title,
                type=h.page.type,
                summary=h.page.summary,
                score=h.score,
                body=h.page.body,
                updated_at=h.page.updated_at,
            )
            for h in outcome.hits
        ],
        context_block=render_context_block(outcome.hits),
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
    )
