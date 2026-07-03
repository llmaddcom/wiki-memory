"""轻量分词：无外部依赖，中英混排可用。

规则：拉丁/数字连续段按词切（转小写）；CJK 连续段切二元组
（单字段落保留单字）。fuzzy 与 bm25 共用，保证两种策略口径一致。
"""

import re

_ASCII_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _ASCII_WORD.finditer(text):
        tokens.append(m.group(0).lower())
    for m in _CJK_RUN.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens
