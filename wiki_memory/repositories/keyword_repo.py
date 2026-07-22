"""keyword 仓储：关键字倒排通道的写入与清理（纯派生物）。

关键字随固化操作生成落库；页面硬删 / REDACT 重固化时清除链接。
词表行（keyword）不主动回收——空指向的词对召回无影响（无 page_keyword
链接即无候选），留待全量重刷时自然收敛。
"""

from sqlmodel import Session, select

from ..models import Keyword, PageKeyword

# 单页关键字上限（与 PageOp schema 的 maxItems 同值）与单词长度上限。
MAX_KEYWORDS_PER_PAGE = 8
_MAX_TERM_CHARS = 32


def normalize_terms(raw: list) -> list[str]:
    """LLM 产出的 keywords → 规范词表：去空白、去重（保序）、封顶、超长丢弃。"""
    seen: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, str):
            continue
        term = item.strip().lower()
        if not term or len(term) > _MAX_TERM_CHARS or term in seen:
            continue
        seen.append(term)
        if len(seen) >= MAX_KEYWORDS_PER_PAGE:
            break
    return seen


def refresh_for_page(
    session: Session, space_id: int, page_id: int, terms: list[str]
) -> None:
    """整替该页关键字链接：删旧链、按词 get-or-create 词行、建新链。"""
    for link in session.exec(
        select(PageKeyword).where(PageKeyword.page_id == page_id)
    ).all():
        session.delete(link)
    session.flush()
    for term in terms:
        keyword = session.exec(
            select(Keyword).where(Keyword.space_id == space_id, Keyword.term == term)
        ).first()
        if keyword is None:
            keyword = Keyword(space_id=space_id, term=term)
            session.add(keyword)
            session.flush()
        session.add(PageKeyword(keyword_id=keyword.id, page_id=page_id))


def clear_for_page(session: Session, page_id: int) -> None:
    """清除该页全部关键字链接（硬删页面 / REDACT 重固化：出处可能已被删）。"""
    for link in session.exec(
        select(PageKeyword).where(PageKeyword.page_id == page_id)
    ).all():
        session.delete(link)


def clear_for_space(session: Session, space_id: int) -> None:
    """space 级联删除：清词表与全部链接。"""
    keywords = session.exec(
        select(Keyword).where(Keyword.space_id == space_id)
    ).all()
    keyword_ids = [k.id for k in keywords]
    if keyword_ids:
        for link in session.exec(
            select(PageKeyword).where(PageKeyword.keyword_id.in_(keyword_ids))
        ).all():
            session.delete(link)
    for keyword in keywords:
        session.delete(keyword)
