from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务配置。全部可由环境变量 / .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="WIKIMEM_")

    # sqlite 单文件起步；换 Postgres 只需改 URL，如
    # postgresql+psycopg://user:pass@127.0.0.1:5432/wiki_memory
    database_url: str = "sqlite:///./wiki_memory.db"

    # 固化/召回所用 LLM（OpenAI 兼容端点，vLLM 等均可）
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = ""
    llm_timeout_seconds: float = 300.0

    # 设置后所有请求须带 X-API-Key 头；留空则不鉴权（内网/本机模式）
    api_key: str = ""

    # 单次固化最多消费的 pending source 数
    consolidate_max_sources: int = 20


settings = Settings()
