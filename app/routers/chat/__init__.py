from fastapi import APIRouter

from .http import router as http_router
from .websocket import router as websocket_router

router = APIRouter()
router.include_router(http_router)
router.include_router(websocket_router)

__all__ = ["router"]
