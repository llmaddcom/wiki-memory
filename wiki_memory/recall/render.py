"""召回结果 → LLM 对话注入格式（对外契约，详见 docs/contract.md）。

任何上游把 context_block 原样放进对话（system 尾部或当前 user 消息前）
即可让模型带着记忆作答。格式选 XML 风格标签：主流模型对边界标签的
遵循度最好，且与正文 markdown 不冲突。
"""

from ..models import Page
from .base import RecallHit


def render_context_block(hits: list[RecallHit]) -> str:
    if not hits:
        return ""
    parts = ["<recalled_memory>"]
    for h in hits:
        p = h.page
        provisional = ' provisional="true"' if h.provisional else ""
        parts.append(
            f'<memory type="{p.type.value}" slug="{p.slug}" title="{p.title}" '
            f'updated_at="{p.updated_at:%Y-%m-%d}"{provisional}>\n{p.body}\n</memory>'
        )
    parts.append("</recalled_memory>")
    return "\n".join(parts)


def resolve_hook(page: Page) -> tuple[str, bool]:
    """页面钩子文本：hook 为空的存量页降级用 summary 前 20 字（回填期兜底），
    第二个返回值是是否走了降级（对外的 hook_fallback 标记）。"""
    if page.hook:
        return page.hook, False
    return page.summary[:20], True


def render_hook_block(hits: list[RecallHit]) -> str:
    """detail="hook" 的注入格式：每页一行钩子（[[slug]] 供模型点名展开），
    体积远小于全文块，适合渐进披露的逐回合注入。"""
    if not hits:
        return ""
    parts = ["<recalled_memory>"]
    for h in hits:
        p = h.page
        hook, _ = resolve_hook(p)
        when = f"（{p.happened_on:%Y-%m-%d}）" if p.happened_on else ""
        # provisional：未固化的临时命中，无展开页可点名（slug 不带 [[]] 语法）。
        if h.provisional:
            parts.append(f"- {hook}{when}（待固化）")
        else:
            parts.append(f"- [[{p.slug}]] {hook}{when}")
    parts.append("</recalled_memory>")
    return "\n".join(parts)
