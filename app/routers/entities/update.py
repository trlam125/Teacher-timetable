"""Compatibility entry point; implementations live in focused modules."""
from fastapi import APIRouter

router = APIRouter()
from app.routers.entities.entity_updates import router as _router_0
router.include_router(_router_0)
from app.routers.entities.assignment_updates import router as _router_1
router.include_router(_router_1)

__all__ = [
    'router',
]
