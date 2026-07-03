"""路由汇聚：把各资源路由统一挂到应用上。"""

from fastapi import APIRouter

from .routes import consolidation, pages, recall, sources, spaces, ui

api_router = APIRouter()
api_router.include_router(spaces.router, tags=["spaces"])
api_router.include_router(sources.router, tags=["sources"])
api_router.include_router(pages.router, tags=["pages"])
api_router.include_router(consolidation.router, tags=["consolidation"])
api_router.include_router(recall.router, tags=["recall"])
api_router.include_router(ui.router, tags=["ui"])
