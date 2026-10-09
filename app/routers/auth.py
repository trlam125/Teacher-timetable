"""Compatibility entry point; implementations live in focused modules."""
from fastapi import APIRouter

router = APIRouter()
from app.routers.auth_routes.home import router as _router_0
router.include_router(_router_0)
from app.routers.auth_routes.login import router as _router_1
router.include_router(_router_1)
from app.routers.auth_routes.registration import router as _router_2
router.include_router(_router_2)
from app.routers.auth_routes.password_reset import router as _router_3
router.include_router(_router_3)
from app.routers.auth_routes.logout import router as _router_4
router.include_router(_router_4)
from app.routers.auth_routes.email_change import router as _router_5
router.include_router(_router_5)
from app.routers.auth_routes.avatar import router as _router_6
router.include_router(_router_6)

__all__ = [
    'router',
]
