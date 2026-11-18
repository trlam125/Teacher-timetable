"""Combine the account routes while preserving the public router entry point."""
from fastapi import APIRouter

from app.routers.auth_routes.avatar import router as avatar_router
from app.routers.auth_routes.devices import router as devices_router
from app.routers.auth_routes.email_change import router as email_change_router
from app.routers.auth_routes.home import router as home_router
from app.routers.auth_routes.login import router as login_router
from app.routers.auth_routes.login_unlock import router as login_unlock_router
from app.routers.auth_routes.logout import router as logout_router
from app.routers.auth_routes.password_reset import router as password_reset_router
from app.routers.auth_routes.registration import router as registration_router

router = APIRouter()
for account_router in (
    home_router, login_router, registration_router, password_reset_router,
    logout_router, email_change_router, avatar_router, devices_router, login_unlock_router,
):
    router.include_router(account_router)

__all__ = ["router"]
