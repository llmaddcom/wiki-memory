"""出站 HTTP 不吃部署机代理环境变量（trust_env=False）回归测试。

httpx 默认 ``trust_env=True`` 会读 http_proxy/https_proxy，且不认 no_proxy 的 CIDR
写法（``127.0.0.0/8`` 无效），导致本机/内网的 vLLM、embedder 目标也被推给环境代理——
换一台带着残留代理变量的机器私有化部署，固化与语义召回全部失联。这里拦截两条出站
路径的 ``httpx.post`` 调用，断言即便环境声明了代理，call site 也显式关闭 trust_env。
"""

import httpx
import pytest

from wiki_memory.embedding import OpenAICompatEmbedder
from wiki_memory.llm.openai_compat import OpenAICompatLLM

_PROXY_ENV = {
    "HTTP_PROXY": "http://127.0.0.1:8118",
    "http_proxy": "http://127.0.0.1:8118",
    "HTTPS_PROXY": "http://127.0.0.1:8118",
    "https_proxy": "http://127.0.0.1:8118",
    "ALL_PROXY": "http://127.0.0.1:8118",
    "all_proxy": "http://127.0.0.1:8118",
}


@pytest.fixture(autouse=True)
def _proxy_env(monkeypatch):
    for key, value in _PROXY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)


@pytest.fixture()
def captured_trust_env(monkeypatch):
    """拦截 httpx.post，记录每次调用的 trust_env；缺省（未显式传）记为 True。"""
    captured: list[bool] = []

    def fake_post(url, **kwargs):
        captured.append(kwargs.get("trust_env", True))
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
                "data": [{"index": 0, "embedding": [0.1]}],
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    return captured


def test_llm_request_ignores_env_proxy(captured_trust_env):
    llm = OpenAICompatLLM("http://127.0.0.1:8000/v1", "key", "model-x")
    llm.complete("system", "user")
    assert captured_trust_env == [False]


def test_embedder_request_ignores_env_proxy(captured_trust_env):
    embedder = OpenAICompatEmbedder("http://127.0.0.1:9997/v1", "key", "emb-x")
    embedder.embed(["hello"])
    assert captured_trust_env == [False]
