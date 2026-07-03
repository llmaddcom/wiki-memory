"""召回策略契约。

策略输入统一为（active 页面列表, 查询, 上限），输出统一为 RecallOutcome；
不同策略只是排序方式不同，路由层无需感知实现差异。
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..models import Page


@dataclass
class RecallHit:
    page: Page
    score: Optional[float] = None  # llm 策略无分值


@dataclass
class RecallOutcome:
    hits: list[RecallHit] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RecallStrategy(Protocol):
    def retrieve(self, pages: list[Page], query: str, max_pages: int) -> RecallOutcome: ...
