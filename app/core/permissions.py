"""Single fail-closed RBAC evaluator for every application surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.db.models.admin import (
    Admin,
    AdminPermissionOverride,
    AdminRole,
    AdminScope,
    Permission,
    RolePermission,
)


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    admin_id: UUID
    permission: str
    target_user_id: UUID | None = None
    target_plan_code: str | None = None
    target_channel_id: int | None = None
    ticket_id: UUID | None = None
    ban_seconds: int | None = None
    gift_bytes: int | None = None
    recipient_count: int | None = None
    mutating: bool = False
    session_valid: bool = True
    confirmed: bool = False
    distinct_super_admin_approvals: int = 0
    protected_super_admin_change: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    permission: str
    risk_level: str | None = None
    source: str | None = None


class ScopeEvaluator:
    """Evaluate all active scopes; every configured constraint is restrictive."""

    @staticmethod
    def evaluate(
        request: AuthorizationRequest,
        scopes: list[AdminScope],
    ) -> tuple[bool, str]:
        for scope in scopes:
            constraints = scope.constraints_json or {}
            if scope.scope_type == "read_only" and request.mutating:
                return False, "scope_read_only"
            if scope.scope_type == "plans" and request.target_plan_code is not None:
                if request.target_plan_code not in constraints.get("allowed", []):
                    return False, "scope_plan_denied"
            if scope.scope_type == "users" and request.target_user_id is not None:
                allowed = {str(value) for value in constraints.get("allowed", [])}
                if str(request.target_user_id) not in allowed:
                    return False, "scope_user_denied"
            if scope.scope_type == "channels" and request.target_channel_id is not None:
                if request.target_channel_id not in constraints.get("allowed", []):
                    return False, "scope_channel_denied"
            if scope.scope_type == "tickets" and request.ticket_id is not None:
                allowed = {str(value) for value in constraints.get("assigned", [])}
                if str(request.ticket_id) not in allowed:
                    return False, "scope_ticket_denied"
            if scope.scope_type == "ban_limit" and request.ban_seconds is not None:
                if request.ban_seconds > int(constraints.get("maximum_seconds", 0)):
                    return False, "scope_ban_limit"
            if scope.scope_type == "gift_limit" and request.gift_bytes is not None:
                if request.gift_bytes > int(constraints.get("maximum_bytes", 0)):
                    return False, "scope_gift_limit"
            if scope.scope_type == "recipient_limit" and request.recipient_count is not None:
                if request.recipient_count > int(constraints.get("maximum", 0)):
                    return False, "scope_recipient_limit"
        return True, "scope_allowed"


class AuthorizationService:
    def __init__(self, *, now_factory: Any | None = None) -> None:
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def evaluate(
        self,
        session: AsyncSession,
        request: AuthorizationRequest,
        *,
        consume: bool = False,
    ) -> AuthorizationDecision:
        now = self._now_factory()
        result = await session.execute(
            select(Admin, AdminRole)
            .join(AdminRole, Admin.role_id == AdminRole.id)
            .where(Admin.id == request.admin_id, AdminRole.deleted_at.is_(None))
            .with_for_update(of=Admin)
        )
        row = result.one_or_none()
        if row is None:
            return self._deny(request, "admin_not_found")
        admin, role = row

        if request.protected_super_admin_change:
            if not role.is_super_admin:
                return self._deny(request, "super_admin_protection")
            if request.distinct_super_admin_approvals < 2:
                return self._deny(request, "dual_control_required")

        if not request.session_valid:
            return self._deny(request, "session_revoked")
        if admin.status != "active" or admin.suspended_at is not None:
            return self._deny(request, f"admin_{admin.status}")
        if admin.starts_at > now or (admin.ends_at is not None and admin.ends_at <= now):
            return self._deny(request, "admin_expired")
        if (
            admin.max_permission_uses is not None
            and admin.permission_use_count >= admin.max_permission_uses
        ):
            return self._deny(request, "permission_use_limit")

        permission = await session.scalar(
            select(Permission).where(
                Permission.code == request.permission,
                Permission.is_active.is_(True),
            )
        )
        if permission is None:
            return self._deny(request, "permission_unknown")
        if permission.super_admin_only and not role.is_super_admin:
            return self._deny(request, "super_admin_only", permission)

        overrides = list(
            (
                await session.scalars(
                    select(AdminPermissionOverride).where(
                        AdminPermissionOverride.admin_id == admin.id,
                        AdminPermissionOverride.permission_id == permission.id,
                        AdminPermissionOverride.starts_at <= now,
                        or_(
                            AdminPermissionOverride.ends_at.is_(None),
                            AdminPermissionOverride.ends_at > now,
                        ),
                    )
                )
            ).all()
        )
        if any(item.effect == "deny" for item in overrides):
            return self._deny(request, "explicit_deny", permission)

        source: str | None = None
        if any(item.effect == "allow" for item in overrides):
            source = "explicit_allow"
        elif role.is_super_admin:
            source = "super_admin_role"
        else:
            has_role_permission = await session.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if has_role_permission is not None:
                source = "base_role"
        if source is None:
            return self._deny(request, "default_deny", permission)

        scopes = list(
            (
                await session.scalars(
                    select(AdminScope).where(
                        AdminScope.admin_id == admin.id,
                        or_(AdminScope.starts_at.is_(None), AdminScope.starts_at <= now),
                        or_(AdminScope.ends_at.is_(None), AdminScope.ends_at > now),
                    )
                )
            ).all()
        )
        scope_allowed, scope_reason = ScopeEvaluator.evaluate(request, scopes)
        if not scope_allowed:
            return self._deny(request, scope_reason, permission)

        if permission.risk_level in {"high", "critical"} and not request.confirmed:
            return self._deny(request, "confirmation_required", permission)
        if permission.risk_level == "critical" and request.distinct_super_admin_approvals < 2:
            return self._deny(request, "dual_control_required", permission)

        if consume:
            admin.permission_use_count += 1
            await session.flush()
        return AuthorizationDecision(
            allowed=True,
            reason="allowed",
            permission=request.permission,
            risk_level=permission.risk_level,
            source=source,
        )

    async def require(
        self,
        session: AsyncSession,
        request: AuthorizationRequest,
        *,
        consume: bool = False,
    ) -> AuthorizationDecision:
        decision = await self.evaluate(session, request, consume=consume)
        if not decision.allowed:
            raise PermissionDenied(
                decision.reason,
                context={"permission": request.permission, "reason": decision.reason},
            )
        return decision

    @staticmethod
    def _deny(
        request: AuthorizationRequest,
        reason: str,
        permission: Permission | None = None,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=False,
            reason=reason,
            permission=request.permission,
            risk_level=None if permission is None else permission.risk_level,
        )
