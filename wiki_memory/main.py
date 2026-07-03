"""应用入口：装配 FastAPI、建表、挂路由。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.router import api_router
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="wiki-memory",
    description=(
        "Wiki 式长期记忆服务：不可变 source 经 LLM 固化为分型、互链、"
        "带修订历史的 wiki；召回策略可选（fuzzy/bm25/llm）；/ui 记忆预览。"
    ),
    lifespan=lifespan,
)
app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}
