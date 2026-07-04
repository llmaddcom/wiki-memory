"""按上游来源删除（delete-by-source）：隐私删除语义的落地。

上游删除会话时，须连带遗忘由该会话沉淀的记忆（数据主权优先于"记忆
不可删"的拟人比喻）。按 external_ref 子集匹配命中 source 后：

- source **硬删除**（content 是含隐私的全文快照，tombstone 不满足删除语义）；
- 经 Evidence 回收受影响页面：全部证据都来自被删 source 的页面连同
  修订历史一起删除（修订正文可能引述被删内容）；仍有其余证据的页面
  剔除对应 evidence 行并用剩余 source 重写正文（针对性重固化）。

只回收**直接证据**：[[链接]] 与既往合并产生的间接影响不追溯（追溯会
退化为删全库）；指向被删页面的链接变悬空，交给后续固化清理。
边界契约见 docs/contract.md。

原子性：重固化的 LLM 调用全部先行完成，任何一页失败则整个请求失败、
库无任何变更，上游可重试——不会出现"source 删了、页面还留着原文"的中间态。
"""

import json
from dataclasses import dataclass, field

from sqlmodel import Session, select

from .consolidation import prompts
from .consolidation.engine import parse_json_object
from .linking import extract_link_slugs
from .llm.base import ChatLLM, LLMError
from .models import (
    ConsolidationRun,
    Evidence,
    Page,
    PageLink,
    PageRevision,
    RevisionTrigger,
    RunStatus,
    Source,
    Space,
    utcnow,
)
from .repositories import evidence_repo, link_repo, revision_repo, run_repo


class RedactionError(Exception):
    """重固化失败（LLM 不可用或输出垃圾）：整个删除请求原子回退。"""


@dataclass
class DeletionImpact:
    """预览与执行共用的影响面：命中的 source 与两类受影响页面。"""

    sources: list[Source]
    pages_to_delete: list[Page]
    pages_to_reconsolidate: list[Page]
    # 混合页 id → 剩余证据的 source id（重固化材料 + 新修订的出处链）
    remaining_by_page: dict[int, set[int]] = field(default_factory=dict)

    @property
    def source_ids(self) -> set[int]:
        return {s.id for s in self.sources}


def match_sources(session: Session, space_id: int, ref: dict) -> list[Source]:
    """external_ref 子集匹配：ref 的每个键值都与 source.external_ref 一致才命中。

    服务不解释 ref 内容（与 ingest 侧约定一致），上游至少应传
    system + session_id，避免误伤其他系统的同名 id。
    """
    sources = session.exec(select(Source).where(Source.space_id == space_id)).all()
    return [
        s
        for s in sources
        if s.external_ref and all(s.external_ref.get(k) == v for k, v in ref.items())
    ]


def assess(session: Session, space_id: int, ref: dict) -> DeletionImpact:
    """算影响面：命中 source + 按直接证据把受影响页面分成"将删除/将重固化"两类。"""
    sources = match_sources(session, space_id, ref)
    impact = DeletionImpact(sources=sources, pages_to_delete=[], pages_to_reconsolidate=[])
    if not sources:
        return impact

    rows = session.exec(
        select(Page, Evidence.source_id)
        .where(Page.space_id == space_id)
        .where(PageRevision.page_id == Page.id)
        .where(Evidence.revision_id == PageRevision.id)
    ).all()
    evidence_by_page: dict[int, set[int]] = {}
    page_by_id: dict[int, Page] = {}
    for page, source_id in rows:
        page_by_id[page.id] = page
        evidence_by_page.setdefault(page.id, set()).add(source_id)

    matched = impact.source_ids
    for page_id, cited in sorted(evidence_by_page.items()):
        if not (cited & matched):
            continue
        remaining = cited - matched
        if remaining:
            impact.pages_to_reconsolidate.append(page_by_id[page_id])
            impact.remaining_by_page[page_id] = remaining
        else:
            impact.pages_to_delete.append(page_by_id[page_id])
    return impact


def execute(session: Session, space: Space, ref: dict, llm: ChatLLM) -> dict:
    """执行删除，返回审计汇总（删除 source 数、删除/重固化页面 slug、run id）。"""
    impact = assess(session, space.id, ref)
    if not impact.sources:
        return {
            "deleted_sources": 0,
            "deleted_pages": [],
            "reconsolidated_pages": [],
            "run_id": None,
        }

    run = run_repo.create(
        session, space.id, "delete_by_source", sorted(impact.source_ids)
    )
    try:
        rewrites = _redact_all(session, llm, run, impact)
    except (LLMError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        run_repo.finish(session, run, RunStatus.failed, error=f"{type(e).__name__}: {e}")
        raise RedactionError(str(e)) from e

    _apply(session, space, run, impact, rewrites)
    touched = [p.slug for p in impact.pages_to_delete + impact.pages_to_reconsolidate]
    run_repo.finish(session, run, RunStatus.succeeded, pages_touched=touched)
    return {
        "deleted_sources": len(impact.sources),
        "deleted_pages": [p.slug for p in impact.pages_to_delete],
        "reconsolidated_pages": [p.slug for p in impact.pages_to_reconsolidate],
        "run_id": run.id,
    }


# -- 内部实现 ------------------------------------------------------------


def _redact_all(
    session: Session, llm: ChatLLM, run: ConsolidationRun, impact: DeletionImpact
) -> dict[int, dict]:
    """先把全部重固化 LLM 调用做完（不动库），保证失败可整体回退。"""
    rewrites: dict[int, dict] = {}
    for page in impact.pages_to_reconsolidate:
        remaining = list(
            session.exec(
                select(Source).where(Source.id.in_(impact.remaining_by_page[page.id]))
            ).all()
        )
        res = llm.complete(
            prompts.REDACT_SYSTEM,
            f"## 页面当前全文\n{prompts.render_pages_full([page])}\n\n"
            f"## 剩余证据材料\n{prompts.render_sources(remaining)}",
        )
        run.prompt_tokens += res.prompt_tokens
        run.completion_tokens += res.completion_tokens
        rewrite = parse_json_object(res.text)
        if not rewrite.get("body"):
            raise ValueError(f"redact output for page {page.slug!r} has no body")
        rewrites[page.id] = rewrite
    return rewrites


def _apply(
    session: Session,
    space: Space,
    run: ConsolidationRun,
    impact: DeletionImpact,
    rewrites: dict[int, dict],
) -> None:
    matched = impact.source_ids

    # 1. 剔除指向被删 source 的全部 evidence 行（覆盖两类页面的所有修订）
    for ev in session.exec(select(Evidence).where(Evidence.source_id.in_(matched))).all():
        session.delete(ev)

    # 2. 全部证据都来自被删 source 的页面：连修订历史一起硬删；
    #    指向它的链接置为悬空（不是错误，交给后续固化清理）
    for page in impact.pages_to_delete:
        for rev in session.exec(
            select(PageRevision).where(PageRevision.page_id == page.id)
        ).all():
            session.delete(rev)
        for link in session.exec(
            select(PageLink).where(PageLink.from_page_id == page.id)
        ).all():
            session.delete(link)
        for link in session.exec(
            select(PageLink).where(PageLink.to_page_id == page.id)
        ).all():
            link.to_page_id = None
            session.add(link)
        session.delete(page)

    # 3. 仍有其余证据的页面：用重写结果落新修订，出处指回剩余 source
    for page in impact.pages_to_reconsolidate:
        rewrite = rewrites[page.id]
        page.title = rewrite.get("title") or page.title
        page.summary = rewrite.get("summary") or page.summary
        page.body = rewrite["body"]
        if rewrite.get("confidence") is not None:
            page.confidence = rewrite["confidence"]
        page.updated_at = utcnow()
        rev = revision_repo.add(
            session,
            page,
            "来源隐私删除后重固化：剔除被删证据，按剩余材料重写",
            RevisionTrigger.consolidation,
            run_id=run.id,
        )
        evidence_repo.add_many(
            session, rev.id, sorted(impact.remaining_by_page[page.id])
        )
        link_repo.refresh_for_page(
            session, space.id, page, extract_link_slugs(page.body)
        )

    # 4. source 硬删除（隐私全文快照随之消失）
    for source in impact.sources:
        session.delete(source)

    link_repo.resolve_dangling(session, space.id)
    session.commit()
