"""[[链接]] 解析与 slug 规范。

正文里写 [[slug]] 或 [[slug|显示文字]]；slug 统一 kebab-case。
悬空链接（指向不存在的页）是合法信号，不是错误。
"""

import re
import unicodedata

_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^\w\-一-鿿]", "", text)
    return text.strip("-")


def extract_link_slugs(body: str) -> list[str]:
    seen: list[str] = []
    for m in _LINK_RE.finditer(body):
        slug = slugify(m.group(1))
        if slug and slug not in seen:
            seen.append(slug)
    return seen
