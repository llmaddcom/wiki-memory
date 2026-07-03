"""召回结果 → LLM 对话注入格式（对外契约，详见 docs/contract.md）。

任何上游把 context_block 原样放进对话（system 尾部或当前 user 消息前）
即可让模型带着记忆作答。格式选 XML 风格标签：主流模型对边界标签的
遵循度最好，且与正文 markdown 不冲突。
"""

from .base import RecallHit


def render_context_block(hits: list[RecallHit]) -> str:
    if not hits:
        return ""
    parts = ["<recalled_memory>"]
    for h in hits:
        p = h.page
        parts.append(
            f'<memory type="{p.type.value}" slug="{p.slug}" title="{p.title}" '
            f'updated_at="{p.updated_at:%Y-%m-%d}">\n{p.body}\n</memory>'
        )
    parts.append("</recalled_memory>")
    return "\n".join(parts)
