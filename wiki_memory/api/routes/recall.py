"""召回路由：按选定策略检索页面，返回命中 + 可直接注入对话的 context_block。

method：fuzzy（模糊词频）/ bm25（默认，速度与质量的平衡）/ llm（最准最慢）/
embedding（语义向量，需配置 embedder）。
detail：full（默认，页面全文）/ hook（轻量钩子行，渐进披露的逐回合注入）。
排序算法与 detail 无关（全字段计分），hook 只是响应裁剪。

三条叠加信号（只加分，不门控）：
- 关键字倒排（bm25 档）：命中关键字的页并入候选集并按指向页面数降权加分；
  计算失败静默降级为纯 BM25。
- 高 salience pending 临时召回（bm25/fuzzy 档）：待固化材料以临时文档参与
  现算，命中标 provisional（冷启动真空兜底），固化后自然退出。
- usage 记账：真实页面命中即 hit_count+1 / last_hit_at（增量累加，绝不覆盖）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...config import settings
from ...db import get_session
from ...llm import ChatLLM
from ...models import Page, PageType, Source, SourceStatus, Space, utcnow
from ...recall import render_context_block, render_hook_block, resolve_hook
from ...recall.bm25 import normalize_score, raw_scores, sort_hits
from ...recall.base import RecallHit, RecallOutcome
from ...recall.keywords import keyword_boosts
from ...recall.llm import RecallError
from ...recall.tokenize import tokenize
from ...repositories import page_repo, source_repo
from ...embedding import OpenAICompatEmbedder
from .. import schemas
from ..deps import (
    build_recall_strategy,
    get_embedder,
    get_llm,
    get_space,
    require_api_key,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

# 关键字 boost 的最大加分（与 recall/keywords 的 _BOOST_SCALE 同值，自适应分母用）。
_KEYWORD_MAX_BOOST = 0.5


@router.post("/spaces/{space_uid}/recall", response_model=schemas.RecallResponse)
def recall(
    payload: schemas.RecallRequest,
    space: Space = Depends(get_space),
    session: Session = Depends(get_session),
    llm: ChatLLM = Depends(get_llm),
    embedder: OpenAICompatEmbedder | None = Depends(get_embedder),
):
    pages = page_repo.list_active(session, space.id)
    provisional_pages = (
        _provisional_pages(session, space.id)
        if payload.method in ("bm25", "fuzzy")
        else []
    )
    try:
        if payload.method == "bm25":
            outcome = _bm25_with_keywords(
                session, space.id, pages, provisional_pages, payload.query, payload.max_pages
            )
        else:
            strategy = build_recall_strategy(payload.method, llm, session, embedder)
            outcome = strategy.retrieve(
                pages + provisional_pages, payload.query, payload.max_pages
            )
            for hit in outcome.hits:
                hit.provisional = hit.page.id is None
    except RecallError as e:
        raise HTTPException(status_code=502, detail=f"recall LLM failed: {e}")

    _record_usage(session, outcome.hits)

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
                    score_details=h.score_details,
                    provisional=h.provisional,
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
                score_details=h.score_details,
                provisional=h.provisional,
                body=h.page.body,
                updated_at=h.page.updated_at,
            )
            for h in outcome.hits
        ],
        context_block=render_context_block(outcome.hits),
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
    )


# -- 内部实现 ------------------------------------------------------------


def _bm25_with_keywords(
    session: Session,
    space_id: int,
    pages: list[Page],
    provisional_pages: list[Page],
    query: str,
    max_pages: int,
) -> RecallOutcome:
    """BM25 归一分 + 关键字并集加分：final = (bm25_norm + boost) / max_possible。

    关键字通道整体 try/except 静默降级（召回退化为纯 BM25）；分母自适应——
    query 未命中任何关键字时为 1.0，不稀释纯 BM25 分。
    """
    all_pages = pages + provisional_pages
    term_count = len(tokenize(query))
    try:
        boosts = keyword_boosts(session, space_id, query)
    except Exception:  # noqa: BLE001 - 信号通道故障绝不阻断召回主路径
        boosts = {}
    max_possible = 1.0 + (_KEYWORD_MAX_BOOST if boosts else 0.0)

    hits: list[RecallHit] = []
    seen_page_ids: set[int] = set()
    for page, raw in raw_scores(all_pages, query):
        norm = normalize_score(raw, term_count)
        boost = boosts.get(page.id, 0.0) if page.id is not None else 0.0
        final = round((norm + boost) / max_possible, 4)
        if page.id is not None:
            seen_page_ids.add(page.id)
        hits.append(
            RecallHit(
                page=page,
                score=final,
                score_details={
                    "bm25_raw": round(raw, 4),
                    "bm25_norm": round(norm, 4),
                    "keyword_boost": round(boost, 4),
                    "max_possible": max_possible,
                    "final": final,
                },
                provisional=page.id is None,
            )
        )
    # 并集：关键字直达但 BM25 为 0 的页也进候选（底分 = boost / max_possible），
    # 无主信号兜底的系统必须给直达页出场机会，不得被词面 miss 静默隐藏。
    for page in pages:
        if page.id in boosts and page.id not in seen_page_ids:
            boost = boosts[page.id]
            final = round(boost / max_possible, 4)
            hits.append(
                RecallHit(
                    page=page,
                    score=final,
                    score_details={
                        "bm25_raw": 0.0,
                        "bm25_norm": 0.0,
                        "keyword_boost": round(boost, 4),
                        "max_possible": max_possible,
                        "final": final,
                    },
                )
            )
    sort_hits(hits)
    return RecallOutcome(hits=hits[:max_pages])


def _provisional_pages(session: Session, space_id: int) -> list[Page]:
    """salience ≥ 阈值的 pending source → 临时文档（不落库，只参与本次现算）。"""
    threshold = settings.pending_recall_min_salience
    if threshold > 1.0:
        return []  # 阈值 >1 即通道关闭
    pending = [
        s
        for s in source_repo.list_by_space(session, space_id, status=SourceStatus.pending)
        if s.salience >= threshold
    ]
    return [_source_as_page(s) for s in pending]


def _source_as_page(source: Source) -> Page:
    """pending source 的临时页视图：id=None 是 provisional 的判定标记。"""
    content = source.content.strip()
    return Page(
        space_id=source.space_id,
        type=PageType.belief,
        slug=f"pending-{source.id}",
        title=content[:40],
        hook=content[:20],
        happened_on=source.occurred_at.date() if source.occurred_at else None,
        summary=content[:300],
        body=content,
    )


def _record_usage(session: Session, hits: list[RecallHit]) -> None:
    """真实页面命中的 usage 记账：增量累加，绝不整列覆盖；provisional 不记。"""
    recorded = False
    for hit in hits:
        if hit.page.id is None:
            continue
        hit.page.hit_count += 1
        hit.page.last_hit_at = utcnow()
        session.add(hit.page)
        recorded = True
    if recorded:
        session.commit()
