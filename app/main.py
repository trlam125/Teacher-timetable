from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.errors import register_exception_handlers
from app.services.runtime import initialize_database, run_database_bootstrap_step
from app.routers.system import router as system_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.admin import router as admin_router
from app.routers.projects import router as projects_router
from app.routers.audit import router as audit_router
from app.routers.chatbot import router as chatbot_router
from app.routers.entities import router as entities_router
from app.routers.constraints import router as constraints_router
from app.routers.schedule import router as schedule_router
from app.routers.teacher import router as teacher_router
from app.routers.share_export import router as share_export_router


def create_app() -> FastAPI:
    app = FastAPI(title="Teacher Timetable")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    register_exception_handlers(app)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    app.include_router(projects_router)
    app.include_router(audit_router)
    app.include_router(chatbot_router)
    app.include_router(entities_router)
    app.include_router(constraints_router)
    app.include_router(schedule_router)
    app.include_router(teacher_router)
    app.include_router(share_export_router)
    return app


run_database_bootstrap_step(initialize_database)
app = create_app()
