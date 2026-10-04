from fastapi import APIRouter

from .fixed import router as fixed_router
from .generation import router as generation_router
from .editor import router as editor_router
from .data import router as data_router

router = APIRouter()
router.include_router(fixed_router)
router.include_router(generation_router)
router.include_router(editor_router)
router.include_router(data_router)

__all__ = ["router"]
