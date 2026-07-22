"""语义召回策略：页级短向量（hook+summary）余弦排序。

向量是纯派生物、惰性维护：召回时缺失/身份不符（model_tag 或维度变了）的页
现场补算并落库，固化/REDACT/回滚等写点只负责失效（删行）。首次查询或换
embedder 后的第一跑会慢（全量补算），之后毫秒级。

分数 = (cos+1)/2 归一到 [0,1]，与 BM25 归一分同量纲；平分 tie-break 与
BM25 同款（happened_on 新者优先）。embedder 故障抛 RecallError 由路由转 502。
"""

from sqlmodel import Session, select

from ..embedding import EmbedderError, OpenAICompatEmbedder
from ..models import Page, PageEmbedding, utcnow
from .base import RecallHit, RecallOutcome
from .bm25 import sort_hits
from .llm import RecallError


def embedding_text(page: Page) -> str:
    """页 → 待 embed 文本：只取 hook+summary（高密度检索面，正文靠下钻）。"""
    return f"{page.hook}\n{page.summary}".strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingRecall:
    """需要 DB 会话（读写 page_embedding 缓存），由路由层现场装配。"""

    def __init__(self, embedder: OpenAICompatEmbedder, session: Session):
        self._embedder = embedder
        self._session = session

    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome:
        if not pages or not query.strip():
            return RecallOutcome()
        try:
            query_vector = self._embedder.embed([query])[0]
            vectors = self._page_vectors(pages, dim=len(query_vector))
        except EmbedderError as e:
            raise RecallError(str(e)) from e

        hits: list[RecallHit] = []
        for page in pages:
            vector = vectors.get(page.id)
            if vector is None:
                continue  # 补算失败的页本轮跳过，不阻断其余命中
            cos = _cosine(query_vector, vector)
            score = round((cos + 1.0) / 2.0, 4)
            hits.append(
                RecallHit(
                    page=page,
                    score=score,
                    score_details={
                        "embedding_cos": round(cos, 4),
                        "final": score,
                        "model_tag": self._embedder.model_tag,
                    },
                )
            )
        sort_hits(hits)
        return RecallOutcome(hits=hits[:max_pages])

    # -- 内部 ------------------------------------------------------------

    def _page_vectors(self, pages: list[Page], dim: int) -> dict[int, list[float]]:
        """读缓存 + 惰性补算：身份不符（model_tag/维度）的行现场重算落库。"""
        page_ids = [p.id for p in pages if p.id is not None]
        rows = self._session.exec(
            select(PageEmbedding).where(PageEmbedding.page_id.in_(page_ids))
        ).all() if page_ids else []
        by_page: dict[int, PageEmbedding] = {r.page_id: r for r in rows}

        vectors: dict[int, list[float]] = {}
        stale: list[Page] = []
        for page in pages:
            row = by_page.get(page.id)
            if (
                row is not None
                and row.model_tag == self._embedder.model_tag
                and row.dim == dim
            ):
                vectors[page.id] = row.vector
            else:
                stale.append(page)

        if stale:
            fresh = self._embedder.embed([embedding_text(p) for p in stale])
            for page, vector in zip(stale, fresh):
                vectors[page.id] = vector
                row = by_page.get(page.id)
                if row is None:
                    row = PageEmbedding(
                        page_id=page.id,
                        space_id=page.space_id,
                        model_tag=self._embedder.model_tag,
                        dim=len(vector),
                        vector=vector,
                    )
                else:
                    row.model_tag = self._embedder.model_tag
                    row.dim = len(vector)
                    row.vector = vector
                    row.updated_at = utcnow()
                self._session.add(row)
            self._session.commit()
        return vectors
