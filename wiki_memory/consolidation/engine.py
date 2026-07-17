"""固化引擎："睡眠"过程本体，wiki 唯一的常规写通路。

两阶段：
1. select —— 给 LLM 索引 + sources，选出需要读全文的已有页面（宁少勿多）。
2. write  —— 给 LLM 索引 + sources + 相关页全文，产出 create/update/archive 操作。

引擎经仓储层落库：写修订、记出处、重解析 [[链接]]、悬空愈合、
更新 source 状态、留 run 日志。LLM 输出垃圾时 run 标 failed、
source 保持 pending 可重试；产出零操作是合法结果（遗忘是功能）。
"""

import json
import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel
from sqlmodel import Session

from ..linking import extract_link_slugs, slugify
from ..llm.base import ChatLLM, LLMError
from ..models import (
    ConsolidationRun,
    Page,
    PageStatus,
    PageType,
    RevisionTrigger,
    RunStatus,
    Source,
    Space,
    utcnow,
)
from ..repositories import (
    evidence_repo,
    link_repo,
    page_repo,
    revision_repo,
    run_repo,
    source_repo,
)
from . import prompts


def parse_json_object(text: str) -> dict:
    """宽容解析：剥掉 code fence / 前后废话，取第一个 { 到最后一个 }。

    response_format 约束下输出天然是纯 JSON；端点不支持时降级为纯文本模式，
    本函数兜底两条路径。
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


# -- 结构化输出 schema（只用于生成 response_format 的 json_schema，------------
# -- 解析仍走 parse_json_object → dict，结构化与降级两条路径同一套代码）------


class PageOp(BaseModel):
    op: Literal["create", "update", "archive"]
    type: PageType = PageType.belief
    slug: str
    title: str = ""
    hook: str = ""  # ≤20 字关键点（语义校验在代码：超长截断）
    happened_on: Optional[str] = None  # YYYY-MM-DD，无则 null（非法置空）
    summary: str = ""
    body: str = ""
    confidence: Optional[float] = None
    change_reason: str = ""
    source_ids: list[int] = []


class WritePlan(BaseModel):
    operations: list[PageOp]


class SelectPlan(BaseModel):
    read: list[str]


def _json_schema_format(name: str, model: type[BaseModel]) -> dict:
    """OpenAI 兼容 response_format：约束解码按 schema 出 JSON（vLLM json_schema）。"""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": model.model_json_schema()},
    }


def _parse_happened_on(value) -> date | None:
    """happened_on 语义校验：非 YYYY-MM-DD 的值一律置空，不丢弃整个操作。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


class ConsolidationEngine:
    def __init__(self, llm: ChatLLM):
        self._llm = llm

    def run(
        self,
        session: Session,
        space: Space,
        trigger: str = "manual",
        max_sources: int = 20,
    ) -> ConsolidationRun:
        # space 级互斥：上游可能并发触发（新会话/上下文压缩/夜间批处理撞车），同一批
        # pending 材料只该被蒸馏一次。发现进行中的固化直接返回它（幂等语义）；
        # 超过陈旧阈值的 running 视为死运行（进程崩溃残留），放行新跑。
        active = run_repo.find_active(session, space.id, stale_seconds=1800)
        if active is not None:
            return active

        pending = source_repo.list_pending(session, space.id, max_sources)
        run = run_repo.create(session, space.id, trigger, [s.id for s in pending])

        if not pending:
            return run_repo.finish(session, run, RunStatus.succeeded, pages_touched=[])

        try:
            touched = self._consolidate(session, space, run, pending)
            return run_repo.finish(session, run, RunStatus.succeeded, pages_touched=touched)
        except (LLMError, json.JSONDecodeError, KeyError, ValueError) as e:
            session.rollback()
            return run_repo.finish(
                session, run, RunStatus.failed, error=f"{type(e).__name__}: {e}"
            )

    # -- 内部实现 --------------------------------------------------------

    def _consolidate(
        self, session: Session, space: Space, run: ConsolidationRun, pending: list[Source]
    ) -> list[str]:
        active_pages = page_repo.list_active(session, space.id)
        index_text = prompts.render_index(active_pages)
        sources_text = prompts.render_sources(pending)

        # 阶段一：选出需要读全文的页面（wiki 为空时跳过）
        context_pages: list[Page] = []
        if active_pages:
            res = self._llm.complete(
                prompts.CONSOLIDATE_SELECT_SYSTEM,
                f"## wiki 索引\n{index_text}\n\n## 最近经历\n{sources_text}",
                response_format=_json_schema_format("select_plan", SelectPlan),
            )
            run.prompt_tokens += res.prompt_tokens
            run.completion_tokens += res.completion_tokens
            slugs = parse_json_object(res.text).get("read", [])
            by_slug = {p.slug: p for p in active_pages}
            context_pages = [by_slug[s] for s in slugs if s in by_slug]

        # 阶段二：产出操作
        res = self._llm.complete(
            prompts.CONSOLIDATE_SYSTEM,
            f"## wiki 索引\n{index_text}\n\n"
            f"## 相关页面全文\n{prompts.render_pages_full(context_pages)}\n\n"
            f"## 最近经历\n{sources_text}",
            response_format=_json_schema_format("write_plan", WritePlan),
        )
        run.prompt_tokens += res.prompt_tokens
        run.completion_tokens += res.completion_tokens
        operations = parse_json_object(res.text).get("operations", [])

        valid_ids = {s.id for s in pending}
        consumed: set[int] = set()
        touched: list[str] = []
        for op in operations:
            source_ids = [i for i in op.get("source_ids", []) if i in valid_ids]
            slug = self._apply_op(session, space, run, op, source_ids)
            if slug:
                touched.append(slug)
                consumed.update(source_ids)

        link_repo.resolve_dangling(session, space.id)
        source_repo.mark_consumed(session, pending, consumed)
        session.commit()
        return touched

    def _apply_op(
        self,
        session: Session,
        space: Space,
        run: ConsolidationRun,
        op: dict,
        source_ids: list[int],
    ) -> str | None:
        kind = op.get("op")
        slug = slugify(op.get("slug", ""))
        if not slug or kind not in ("create", "update", "archive"):
            return None

        page = page_repo.get_by_slug(session, space.id, slug)
        reason = op.get("change_reason", "")

        if kind == "archive":
            if page is None or page.status == PageStatus.archived:
                return None
            page.status = PageStatus.archived
            page.updated_at = utcnow()
            self._record(session, page, run, reason or "归档", source_ids)
            return slug

        title = op.get("title") or slug
        # 语义校验在代码不在 schema：坏字段修剪后照常落库，不丢弃整个操作
        hook = (op.get("hook") or "").strip()[:20]
        happened_on = _parse_happened_on(op.get("happened_on"))
        summary = op.get("summary") or ""
        body = op.get("body") or ""
        confidence = op.get("confidence")

        if page is None:
            page = Page(
                space_id=space.id,
                type=PageType(op.get("type", PageType.belief.value)),
                slug=slug,
                title=title,
                hook=hook,
                happened_on=happened_on,
                summary=summary,
                body=body,
                confidence=confidence,
            )
            session.add(page)
            session.flush()
            reason = reason or "建页"
        else:
            page.title = title
            page.hook = hook
            page.happened_on = happened_on
            page.summary = summary
            page.body = body
            if confidence is not None:
                page.confidence = confidence
            page.status = PageStatus.active
            page.updated_at = utcnow()
            reason = reason or "更新"

        self._record(session, page, run, reason, source_ids)
        link_repo.refresh_for_page(session, space.id, page, extract_link_slugs(page.body))
        return slug

    def _record(
        self,
        session: Session,
        page: Page,
        run: ConsolidationRun,
        reason: str,
        source_ids: list[int],
    ) -> None:
        rev = revision_repo.add(
            session, page, reason, RevisionTrigger.consolidation, run_id=run.id
        )
        evidence_repo.add_many(session, rev.id, source_ids)
