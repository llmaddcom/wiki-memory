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

    # 语义召回 embedder（OpenAI 兼容 /embeddings 端点）；api_base 留空 = 通道关闭，
    # recall method=embedding 将返回 422。model 名同时是向量身份标（换模型自动失效重算）。
    embedder_api_base: str = ""
    embedder_api_key: str = "EMPTY"
    embedder_model: str = ""
    embedder_timeout_seconds: float = 30.0

    # 高显著性 pending source 临时召回（冷启动真空兜底）：salience ≥ 阈值的待固化
    # 材料以临时文档参与 BM25 现算并标 provisional；固化后自然退出。只开高显著性
    # 窄口——普通回合原文词袋噪声大，全量开会污染召回。
    pending_recall_min_salience: float = 0.8


settings = Settings()
