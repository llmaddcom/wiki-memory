"""page_embedding 仓储：向量缓存的失效清理。

写点（固化改写 / REDACT / 回滚 / 硬删）只做失效（删行），补算发生在
召回读路径（惰性重刷）——写路径绝不同步调用 embedder。
"""

from sqlmodel import Session, select

from ..models import PageEmbedding


def invalidate_for_page(session: Session, page_id: int) -> None:
    for row in session.exec(
        select(PageEmbedding).where(PageEmbedding.page_id == page_id)
    ).all():
        session.delete(row)


def clear_for_space(session: Session, space_id: int) -> None:
    for row in session.exec(
        select(PageEmbedding).where(PageEmbedding.space_id == space_id)
    ).all():
        session.delete(row)
