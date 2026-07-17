import httpx

from .base import ChatResult, LLMError


class OpenAICompatLLM:
    """OpenAI 兼容 /chat/completions 适配器（vLLM、各中转均可）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 300.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def complete(
        self, system: str, user: str, response_format: dict | None = None
    ) -> ChatResult:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if response_format is not None:
            # 结构化输出优先；端点不支持 response_format（400/501 等）时
            # 降级重试一次纯文本模式，交给上层 parse_json_object 兜底解析。
            try:
                return self._request({**payload, "response_format": response_format})
            except LLMError:
                pass
        return self._request(payload)

    def _request(self, payload: dict) -> ChatResult:
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise LLMError(f"LLM request failed: {e}") from e
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected LLM response shape: {data}") from e
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
