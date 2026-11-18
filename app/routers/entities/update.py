"""Compatibility entry point; implementations live in focused modules."""
from fastapi import APIRouter

from app.routers.entities.assignment_updates import router as assignment_updates_router
from app.routers.entities.entity_updates import router as entity_updates_router

router = APIRouter()
router.include_router(entity_updates_router)
router.include_router(assignment_updates_router)

__all__ = ["router"]
