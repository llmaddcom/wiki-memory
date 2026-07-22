"""召回策略契约。

策略输入统一为（active 页面列表, 查询, 上限），输出统一为 RecallOutcome；
不同策略只是排序方式不同，路由层无需感知实现差异。

score_details 是逐信号计分拆解（可解释可审计的召回侧落点）：各信号原始分/
归一分/合成方式一目了然，也为多信号加和（关键字/usage）调参铺路。llm 策略
无数值分，两字段皆空。
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..models import Page


@dataclass
class RecallHit:
    page: Page
    score: Optional[float] = None  # llm 策略无分值
    score_details: Optional[dict] = None  # 逐信号计分拆解（llm 策略为空）
    provisional: bool = False  # 高 salience pending 材料的临时命中（未固化）


@dataclass
class RecallOutcome:
    hits: list[RecallHit] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RecallStrategy(Protocol):
    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome: ...
