"""embedder 适配：OpenAI 兼容 /embeddings 端点（可替换轴，引擎只依赖本契约）。

语义召回通道的向量来源。模型名即向量身份标（model_tag）：召回时与落库行
不符的向量视为失效重算，换模型无需人工迁移。
"""

import httpx


class EmbedderError(Exception):
    pass


class OpenAICompatEmbedder:
    def __init__(self, api_base: str, api_key: str, model: str, timeout: float = 30.0):
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self.model_tag = model
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量 embed；返回顺序与输入一致。任何故障收敛为 EmbedderError。"""
        if not texts:
            return []
        try:
            # trust_env=False：连通性只由 api_base 决定，不吃部署机 HTTP(S)_PROXY
            # 环境变量（httpx 不认 no_proxy 的 CIDR 写法，内网/本机目标会被误推给代理）。
            resp = httpx.post(
                f"{self._api_base}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model_tag, "input": texts},
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise EmbedderError(f"embedder request failed: {e}") from e
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            vectors = [row["embedding"] for row in rows]
        except (KeyError, TypeError) as e:
            raise EmbedderError(f"unexpected embedder response shape: {data}") from e
        if len(vectors) != len(texts):
            raise EmbedderError(
                f"embedder returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors
