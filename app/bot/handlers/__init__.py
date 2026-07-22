"""Router builders for user and administrator interactions."""

from app.bot.handlers.admin import build_admin_router
from app.bot.handlers.user import build_user_router

__all__ = ["build_admin_router", "build_user_router"]
