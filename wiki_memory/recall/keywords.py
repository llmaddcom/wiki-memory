"""关键字倒排通道的查询侧：命中匹配 + 降权加分。

原则：**信号只加分，不门控**。关键字命中把页面拉进候选集（与 BM25 并集）
并在归一分之上加 boost，绝不做路由门——否则低信号页会被系统性隐藏。

降权公式（mem0 移植版，系数按单角色库几百页规模重标定）：
    boost = match_quality × scale × 1/(1 + c·(n_pages−1)²)
n_pages 为该关键字指向的 active 页面数；默认 scale=0.5、c=0.01（半衰点在 n≈11，
指向 30+ 页的万能词近乎无效）。工程口径照搬：query 侧关键字去重封顶 8 个、同页
多关键字命中取 max 不累加、整体计算失败静默降级（召回退化为纯 BM25，不报错）。

三个系数都是系统键（config/system.yaml 的 recall.keyword_*），不再散落为模块常量。
"""

from sqlmodel import Session, select

from ..config import system
from ..models import Keyword, Page, PageKeyword, PageStatus


def keyword_boosts(session: Session, space_id: int, query: str) -> dict[int, float]:
    """query 命中的关键字 → {page_id: boost}。任何异常由调用方静默降级。

    匹配口径：关键字 term 作为子串出现在 query（小写化）中即命中——关键字是
    LLM 生成的专名/短语，子串匹配对 CJK 无需分词且不受二元组切分影响。
    """
    lowered = query.lower()
    if not lowered.strip():
        return {}
    keywords = session.exec(
        select(Keyword).where(Keyword.space_id == space_id)
    ).all()
    matched = [k for k in keywords if k.term and k.term in lowered]
    if not matched:
        return {}
    matched = matched[: system.recall_keyword_max_query_terms]

    scale = system.recall_keyword_boost_scale
    coeff = system.recall_keyword_demotion_coeff
    boosts: dict[int, float] = {}
    for keyword in matched:
        rows = session.exec(
            select(PageKeyword.page_id)
            .join(Page, Page.id == PageKeyword.page_id)
            .where(
                PageKeyword.keyword_id == keyword.id,
                Page.status == PageStatus.active,
            )
        ).all()
        n_pages = len(rows)
        if n_pages == 0:
            continue
        boost = scale / (1 + coeff * (n_pages - 1) ** 2)
        for page_id in rows:
            # 同页多关键字命中取 max 不累加。
            boosts[page_id] = max(boosts.get(page_id, 0.0), boost)
    return boosts
