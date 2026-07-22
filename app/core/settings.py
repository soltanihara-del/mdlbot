"""Typed, versioned PostgreSQL settings with transaction-owned updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SettingsConflict, SettingsValidationError
from app.core.permissions import AuthorizationRequest, AuthorizationService
from app.core.redis import RedisManager
from app.db.models.admin import AdminAuditLog, Setting, SettingsHistory, SettingsProfile
from app.db.models.jobs import OutboxEvent


BYTE_UNITS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
}
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
BITRATE_UNITS = {
    "bps": 1,
    "kbps": 1000,
    "mbps": 1000**2,
    "gbps": 1000**3,
}
NUMBER_UNIT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s*$")
DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([smhdw])", re.IGNORECASE)


def _decimal_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise SettingsValidationError("boolean is not a numeric value")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SettingsValidationError("invalid numeric value") from exc
    if not number.is_finite():
        raise SettingsValidationError("numeric value must be finite")
    return number


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _parse_scaled(value: Any, units: dict[str, int], default_unit: str) -> int:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number, unit = _decimal_number(value), default_unit
    else:
        match = NUMBER_UNIT_RE.fullmatch(str(value))
        if match is None:
            raise SettingsValidationError("invalid value/unit syntax")
        number = _decimal_number(match.group(1))
        unit = (match.group(2) or default_unit).lower()
    if unit not in units:
        raise SettingsValidationError("unsupported unit", context={"unit": unit})
    scaled = number * units[unit]
    if scaled != scaled.to_integral_value():
        raise SettingsValidationError("canonical value must be an integer")
    return int(scaled)


def _parse_duration(value: Any) -> int:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _parse_scaled(value, DURATION_UNITS, "s")
    text = str(value).strip().lower()
    parts = list(DURATION_PART_RE.finditer(text))
    if not parts or "".join(part.group(0).replace(" ", "") for part in parts) != text.replace(" ", ""):
        raise SettingsValidationError("invalid duration syntax")
    total = sum(_decimal_number(part.group(1)) * DURATION_UNITS[part.group(2)] for part in parts)
    if total != total.to_integral_value():
        raise SettingsValidationError("duration must resolve to whole seconds")
    return int(total)


def parse_setting_value(setting: Setting, raw_value: Any) -> Any:
    value_type = setting.value_type
    if value_type == "boolean":
        if isinstance(raw_value, bool):
            value = raw_value
        elif str(raw_value).strip().lower() in {"true", "1", "yes", "on"}:
            value = True
        elif str(raw_value).strip().lower() in {"false", "0", "no", "off"}:
            value = False
        else:
            raise SettingsValidationError("invalid boolean value")
    elif value_type == "integer":
        number = _decimal_number(raw_value)
        if number != number.to_integral_value():
            raise SettingsValidationError("integer value required")
        value = int(number)
    elif value_type in {"decimal", "percentage"}:
        value = _json_number(_decimal_number(raw_value))
    elif value_type == "bytes":
        value = _parse_scaled(raw_value, BYTE_UNITS, "b")
    elif value_type == "duration":
        value = _parse_duration(raw_value)
    elif value_type == "bitrate":
        value = _parse_scaled(raw_value, BITRATE_UNITS, "bps")
    elif value_type in {"string", "enum"}:
        value = str(raw_value).strip()
        if not value or len(value) > 4096:
            raise SettingsValidationError("string value is empty or too long")
    elif value_type == "list":
        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                value = [part.strip() for part in raw_value.split(",") if part.strip()]
        else:
            value = raw_value
        if not isinstance(value, list) or len(value) > 1000:
            raise SettingsValidationError("list value required")
    elif value_type == "controlled_json":
        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise SettingsValidationError("invalid JSON") from exc
        else:
            value = raw_value
        if not isinstance(value, (dict, list)):
            raise SettingsValidationError("controlled JSON must be an object or array")
        if len(json.dumps(value, ensure_ascii=False)) > 65536:
            raise SettingsValidationError("controlled JSON exceeds size limit")
    else:
        raise SettingsValidationError("unsupported setting type", context={"type": value_type})

    if setting.allowed_values is not None and value not in setting.allowed_values:
        raise SettingsValidationError(
            "value is not allowed",
            context={"key": setting.key, "allowed": setting.allowed_values},
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = Decimal(str(value))
        if setting.minimum is not None and number < setting.minimum:
            raise SettingsValidationError("value is below minimum", context={"key": setting.key})
        if setting.maximum is not None and number > setting.maximum:
            raise SettingsValidationError("value is above maximum", context={"key": setting.key})
    return value


def validate_cross_setting_invariants(values: Mapping[str, Any]) -> None:
    thresholds = (
        values.get("storage.warning_percent"),
        values.get("storage.stop_percent"),
        values.get("storage.emergency_percent"),
    )
    if all(value is not None for value in thresholds) and not (
        thresholds[0] < thresholds[1] < thresholds[2]
    ):
        raise SettingsValidationError("storage thresholds must be warning < stop < emergency")
    for key in ("downloads.session_ttl", "stream.session_ttl", "security.admin_session_ttl"):
        value = values.get(key)
        if value is not None and not 60 <= value <= 86400:
            raise SettingsValidationError("session lifetime is outside hard safety bounds", context={"key": key})


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    values: Mapping[str, Any]
    versions: Mapping[str, int]
    loaded_at: datetime

    @classmethod
    def from_rows(cls, rows: list[Setting]) -> "SettingsSnapshot":
        values = {row.key: row.value for row in rows if row.is_enabled}
        validate_cross_setting_invariants(values)
        return cls(
            values=MappingProxyType(values),
            versions=MappingProxyType({row.key: row.version for row in rows}),
            loaded_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class SettingChange:
    key: str
    old_value: Any
    new_value: Any
    version: int
    reload_type: str


class SettingsService:
    def __init__(
        self,
        authorization: AuthorizationService,
        redis: RedisManager | None = None,
    ) -> None:
        self._authorization = authorization
        self._redis = redis

    async def get_snapshot(self, session: AsyncSession) -> SettingsSnapshot:
        rows = list((await session.scalars(select(Setting).order_by(Setting.key))).all())
        return SettingsSnapshot.from_rows(rows)

    async def update(
        self,
        session: AsyncSession,
        *,
        admin_id: UUID,
        key: str,
        raw_value: Any,
        expected_version: int,
        reason: str,
        confirmed: bool,
        distinct_super_admin_approvals: int = 0,
    ) -> SettingChange:
        reason = reason.strip()
        if len(reason) < 5 or len(reason) > 2000:
            raise SettingsValidationError("a meaningful bounded reason is required")
        setting = await session.scalar(
            select(Setting).where(Setting.key == key).with_for_update()
        )
        if setting is None or not setting.is_enabled:
            raise SettingsValidationError("setting does not exist or is disabled", context={"key": key})
        if not setting.runtime_editable:
            raise SettingsValidationError("setting is not runtime editable", context={"key": key})
        if setting.version != expected_version:
            raise SettingsConflict(
                "setting version changed",
                context={"key": key, "expected": expected_version, "actual": setting.version},
            )
        await self._authorization.require(
            session,
            AuthorizationRequest(
                admin_id=admin_id,
                permission=setting.required_permission,
                mutating=True,
                confirmed=confirmed,
                distinct_super_admin_approvals=distinct_super_admin_approvals,
                metadata={"setting_key": key, "expected_version": expected_version},
            ),
            consume=True,
        )
        new_value = parse_setting_value(setting, raw_value)
        snapshot = await self.get_snapshot(session)
        proposed = dict(snapshot.values)
        proposed[key] = new_value
        validate_cross_setting_invariants(proposed)
        old_value = setting.value
        new_version = setting.version + 1
        setting.value = new_value
        setting.version = new_version
        session.add(
            SettingsHistory(
                setting_id=setting.id,
                version=new_version,
                old_value=old_value,
                new_value=new_value,
                changed_by_admin_id=admin_id,
                reason=reason,
            )
        )
        session.add(
            AdminAuditLog(
                admin_id=admin_id,
                action="settings.update",
                target_type="setting",
                target_id=str(setting.id),
                permission=setting.required_permission,
                old_value={"value": old_value, "version": expected_version},
                new_value={"value": new_value, "version": new_version},
                reason=reason,
                success=True,
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="setting",
                aggregate_id=setting.id,
                event_type="settings.changed",
                stream_name="settings-events",
                payload={"key": key, "version": new_version, "reload_type": setting.reload_type},
                deduplication_key=f"setting:{setting.id}:version:{new_version}",
                available_at=datetime.now(UTC),
            )
        )
        await session.flush()
        return SettingChange(key, old_value, new_value, new_version, setting.reload_type)

    async def apply_profile(
        self,
        session: AsyncSession,
        *,
        admin_id: UUID,
        profile_code: str,
        expected_versions: Mapping[str, int],
        reason: str,
        confirmed: bool,
        distinct_super_admin_approvals: int = 0,
    ) -> list[SettingChange]:
        reason = reason.strip()
        if len(reason) < 5 or len(reason) > 2000:
            raise SettingsValidationError("a meaningful bounded reason is required")
        profile = await session.scalar(
            select(SettingsProfile).where(
                SettingsProfile.code == profile_code,
                SettingsProfile.deleted_at.is_(None),
            )
        )
        if profile is None:
            raise SettingsValidationError("settings profile does not exist")
        await self._authorization.require(
            session,
            AuthorizationRequest(
                admin_id=admin_id,
                permission="settings.apply_profile",
                mutating=True,
                confirmed=confirmed,
                distinct_super_admin_approvals=distinct_super_admin_approvals,
            ),
            consume=True,
        )
        keys = sorted(profile.values)
        rows = list(
            (
                await session.scalars(
                    select(Setting).where(Setting.key.in_(keys)).order_by(Setting.key).with_for_update()
                )
            ).all()
        )
        if {row.key for row in rows} != set(keys):
            raise SettingsValidationError("profile references missing settings")
        proposed = dict((await self.get_snapshot(session)).values)
        parsed: dict[str, Any] = {}
        for row in rows:
            if row.version != expected_versions.get(row.key):
                raise SettingsConflict("profile setting version changed", context={"key": row.key})
            parsed[row.key] = parse_setting_value(row, profile.values[row.key])
            proposed[row.key] = parsed[row.key]
        validate_cross_setting_invariants(proposed)

        changes: list[SettingChange] = []
        for row in rows:
            old_value = row.value
            row.version += 1
            row.value = parsed[row.key]
            session.add(SettingsHistory(setting_id=row.id, version=row.version, old_value=old_value, new_value=row.value, changed_by_admin_id=admin_id, reason=reason))
            session.add(OutboxEvent(aggregate_type="setting", aggregate_id=row.id, event_type="settings.changed", stream_name="settings-events", payload={"key": row.key, "version": row.version, "profile": profile_code, "reload_type": row.reload_type}, deduplication_key=f"setting:{row.id}:version:{row.version}", available_at=datetime.now(UTC)))
            changes.append(SettingChange(row.key, old_value, row.value, row.version, row.reload_type))
        session.add(AdminAuditLog(admin_id=admin_id, action="settings.apply_profile", target_type="settings_profile", target_id=str(profile.id), permission="settings.apply_profile", old_value={"versions": dict(expected_versions)}, new_value={"profile": profile_code, "changes": [change.key for change in changes]}, reason=reason, success=True))
        await session.flush()
        return changes

    async def invalidate_after_commit(self, changes: list[SettingChange]) -> None:
        """Call only after the surrounding database transaction committed."""

        if self._redis is None or not changes:
            return
        try:
            for change in changes:
                await self._redis.invalidate("settings", item_key=change.key)
        except Exception:
            # Outbox publication and generation polling repair missed best-effort cache invalidation.
            return
