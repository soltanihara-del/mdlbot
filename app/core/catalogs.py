"""Version-controlled RBAC, setting, and profile seed catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal


Risk = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    code: str
    category: str
    name_fa: str
    name_en: str
    description_fa: str
    description_en: str
    risk_level: Risk = "low"
    super_admin_only: bool = False


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    code: str
    name_fa: str
    name_en: str
    description_fa: str
    description_en: str
    permissions: tuple[str, ...]
    is_super_admin: bool = False


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    category: str
    value_type: str
    default: Any
    name_fa: str
    name_en: str
    description_fa: str
    description_en: str
    unit: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    allowed_values: tuple[Any, ...] | None = None
    reload_type: str = "hot_reload"
    required_permission: str = "settings.update"
    runtime_editable: bool = True
    dependencies: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SettingsProfileDefinition:
    code: str
    name_fa: str
    name_en: str
    description_fa: str
    description_en: str
    values: dict[str, Any]


def _permission(
    code: str,
    category: str,
    en: str,
    fa: str,
    risk: Risk = "low",
    *,
    super_only: bool = False,
) -> PermissionDefinition:
    return PermissionDefinition(
        code=code,
        category=category,
        name_fa=fa,
        name_en=en,
        description_fa=f"اجازه {fa} با ثبت کامل رویداد مدیریتی.",
        description_en=f"Allows {en.lower()} with a complete administrative audit record.",
        risk_level=risk,
        super_admin_only=super_only,
    )


PERMISSIONS: tuple[PermissionDefinition, ...] = (
    _permission("dashboard.view", "dashboard", "View dashboard", "مشاهده پیشخوان"),
    _permission("settings.view", "settings", "View settings", "مشاهده تنظیمات"),
    _permission("settings.update", "settings", "Update settings", "ویرایش تنظیمات", "high"),
    _permission("settings.apply_profile", "settings", "Apply settings profile", "اعمال نمایه تنظیمات", "high"),
    _permission("admins.view", "admins", "View administrators", "مشاهده مدیران", "medium"),
    _permission("admins.manage", "admins", "Manage administrators", "مدیریت مدیران", "critical", super_only=True),
    _permission("admins.permissions.manage", "admins", "Manage permissions", "مدیریت دسترسی‌ها", "critical", super_only=True),
    _permission("admins.sessions.revoke", "admins", "Revoke admin sessions", "لغو نشست مدیر", "high"),
    _permission("users.view", "users", "View users", "مشاهده کاربران"),
    _permission("users.manage", "users", "Manage users", "مدیریت کاربران", "medium"),
    _permission("users.restrict", "users", "Restrict users", "محدودسازی کاربران", "high"),
    _permission("users.ban", "users", "Ban users", "مسدودسازی کاربران", "high"),
    _permission("users.quota.manage", "quota", "Manage user quota", "مدیریت سهمیه کاربر", "high"),
    _permission("files.view", "files", "View file metadata", "مشاهده اطلاعات فایل", "medium"),
    _permission("files.delete", "files", "Delete files", "حذف فایل", "high"),
    _permission("files.quarantine", "files", "Quarantine files", "قرنطینه فایل", "high"),
    _permission("public.review", "public", "Review public submissions", "بررسی انتشار عمومی", "medium"),
    _permission("public.publish", "public", "Publish public content", "انتشار محتوای عمومی", "high"),
    _permission("public.takedown", "public", "Take down public content", "حذف محتوای عمومی", "high"),
    _permission("support.view", "support", "View support tickets", "مشاهده تیکت‌ها"),
    _permission("support.reply", "support", "Reply to support tickets", "پاسخ به تیکت‌ها", "medium"),
    _permission("support.assign", "support", "Assign support tickets", "تخصیص تیکت‌ها", "medium"),
    _permission("broadcast.view", "broadcast", "View broadcasts", "مشاهده ارسال همگانی", "medium"),
    _permission("broadcast.manage", "broadcast", "Manage broadcasts", "مدیریت ارسال همگانی", "high"),
    _permission("broadcast.send", "broadcast", "Send broadcasts", "اجرای ارسال همگانی", "critical"),
    _permission("security.view", "security", "View security events", "مشاهده رویدادهای امنیتی", "medium"),
    _permission("security.manage", "security", "Manage security events", "مدیریت رویدادهای امنیتی", "high"),
    _permission("security.false_positive", "security", "Mark false positives", "ثبت تشخیص اشتباه", "high"),
    _permission("audit.view", "audit", "View audit log", "مشاهده گزارش ممیزی", "high"),
    _permission("backup.create", "backup", "Create backup", "ایجاد پشتیبان", "high"),
    _permission("backup.view", "backup", "View backups", "مشاهده پشتیبان‌ها", "medium"),
    _permission("backup.download", "backup", "Download backup", "دریافت پشتیبان", "critical", super_only=True),
    _permission("restore.view", "backup", "View restore operations", "مشاهده بازگردانی‌ها", "medium"),
    _permission("restore.execute", "backup", "Execute restore", "اجرای بازگردانی", "critical", super_only=True),
    _permission("infrastructure.manage", "infrastructure", "Manage infrastructure", "مدیریت زیرساخت", "critical", super_only=True),
    _permission("secrets.rotate", "security", "Rotate secrets", "چرخش اسرار", "critical", super_only=True),
)

_P = {permission.code for permission in PERMISSIONS}
_VIEWER_SET = {code for code in _P if code.endswith(".view") or code == "dashboard.view"}
_VIEWER = tuple(sorted(_VIEWER_SET))

ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition("super_admin", "مدیر ارشد", "Super Admin", "کنترل کامل حفاظت‌شده", "Protected full control", tuple(sorted(_P)), True),
    RoleDefinition("operations", "مدیر عملیات", "Operations Admin", "عملیات روزمره و تنظیمات", "Daily operations and settings", tuple(sorted(_VIEWER_SET | {"settings.update", "settings.apply_profile", "files.delete", "users.manage"}))),
    RoleDefinition("user_manager", "مدیر کاربران", "User Manager", "مدیریت کاربر و سهمیه", "User and quota management", ("dashboard.view", "users.view", "users.manage", "users.restrict", "users.ban", "users.quota.manage")),
    RoleDefinition("content_moderator", "ناظر محتوا", "Content Moderator", "بررسی فایل و کانال عمومی", "File and public-channel moderation", ("dashboard.view", "files.view", "files.quarantine", "public.review", "public.publish", "public.takedown")),
    RoleDefinition("support_agent", "کارشناس پشتیبانی", "Support Agent", "رسیدگی به تیکت‌ها", "Ticket handling", ("dashboard.view", "users.view", "support.view", "support.reply")),
    RoleDefinition("broadcaster", "مدیر اطلاع‌رسانی", "Broadcaster", "مدیریت ارسال‌های همگانی", "Broadcast management", ("dashboard.view", "broadcast.view", "broadcast.manage", "broadcast.send")),
    RoleDefinition("security_auditor", "ممیز امنیت", "Security Auditor", "نظارت امنیتی فقط‌خواندنی", "Read-oriented security oversight", ("dashboard.view", "security.view", "audit.view", "files.view")),
    RoleDefinition("viewer", "ناظر", "Viewer", "دسترسی فقط‌خواندنی", "Read-only access", _VIEWER),
)


def _setting(
    key: str,
    category: str,
    value_type: str,
    default: Any,
    en: str,
    fa: str,
    *,
    unit: str | None = None,
    minimum: int | str | None = None,
    maximum: int | str | None = None,
    allowed: tuple[Any, ...] | None = None,
    reload_type: str = "hot_reload",
    permission: str = "settings.update",
    dependencies: dict[str, Any] | None = None,
) -> SettingDefinition:
    return SettingDefinition(
        key=key,
        category=category,
        value_type=value_type,
        default=default,
        name_fa=fa,
        name_en=en,
        description_fa=f"مقدار معتبر {fa} در سیاست اجرایی سامانه.",
        description_en=f"Validated {en.lower()} used by the runtime policy.",
        unit=unit,
        minimum=None if minimum is None else Decimal(str(minimum)),
        maximum=None if maximum is None else Decimal(str(maximum)),
        allowed_values=allowed,
        reload_type=reload_type,
        required_permission=permission,
        dependencies=dependencies,
    )


SETTINGS: tuple[SettingDefinition, ...] = (
    _setting("system.maintenance", "system", "boolean", False, "Maintenance mode", "حالت نگهداری"),
    _setting("admission.enabled", "system", "boolean", True, "New job admission", "پذیرش کار جدید"),
    _setting("files.max_size", "files", "bytes", 2 * 1024**3, "Maximum file size", "حداکثر اندازه فایل", unit="bytes", minimum=1024**2, maximum=20 * 1024**3),
    _setting("files.retention", "files", "duration", 7 * 86400, "Default retention", "نگهداری پیش‌فرض", unit="seconds", minimum=3600, maximum=365 * 86400),
    _setting("files.concurrent_jobs", "files", "integer", 4, "Concurrent jobs", "کارهای هم‌زمان", minimum=1, maximum=128),
    _setting("queue.max_age", "queue", "duration", 86400, "Maximum queue age", "حداکثر عمر صف", unit="seconds", minimum=300, maximum=7 * 86400),
    _setting("queue.dispatch_batch", "queue", "integer", 50, "Dispatch batch size", "اندازه دسته صف", minimum=1, maximum=1000),
    _setting("downloads.session_ttl", "downloads", "duration", 3600, "Download session lifetime", "عمر نشست دانلود", unit="seconds", minimum=60, maximum=86400),
    _setting("downloads.max_connections", "downloads", "integer", 4, "Download connection limit", "حد اتصال دانلود", minimum=1, maximum=32),
    _setting("downloads.max_range_requests", "downloads", "integer", 1000, "Range request limit", "حد درخواست بازه", minimum=1, maximum=10000),
    _setting("downloads.rate", "downloads", "bitrate", 50_000_000, "Download bitrate", "نرخ دانلود", unit="bits_per_second", minimum=64_000, maximum=10_000_000_000),
    _setting("stream.session_ttl", "stream", "duration", 7200, "Stream session lifetime", "عمر نشست پخش", unit="seconds", minimum=60, maximum=86400),
    _setting("stream.max_connections", "stream", "integer", 2, "Stream connection limit", "حد اتصال پخش", minimum=1, maximum=16),
    _setting("stream.rate", "stream", "bitrate", 20_000_000, "Stream bitrate", "نرخ پخش", unit="bits_per_second", minimum=64_000, maximum=1_000_000_000),
    _setting("security.url_max_redirects", "security", "integer", 5, "URL redirect limit", "حد تغییرمسیر URL", minimum=0, maximum=10),
    _setting("security.url_timeout", "security", "duration", 30, "URL request timeout", "مهلت درخواست URL", unit="seconds", minimum=2, maximum=300),
    _setting("security.scan_required", "security", "boolean", True, "Mandatory malware scan", "اسکن اجباری بدافزار"),
    _setting("security.failed_login_limit", "security", "integer", 5, "Failed login limit", "حد ورود ناموفق", minimum=1, maximum=20),
    _setting("security.admin_session_ttl", "security", "duration", 1800, "Admin session lifetime", "عمر نشست مدیر", unit="seconds", minimum=300, maximum=86400),
    _setting("storage.warning_percent", "storage", "percentage", 80, "Storage warning threshold", "آستانه هشدار فضا", unit="percent", minimum=1, maximum=99),
    _setting("storage.stop_percent", "storage", "percentage", 90, "Storage admission-stop threshold", "آستانه توقف پذیرش", unit="percent", minimum=2, maximum=99),
    _setting("storage.emergency_percent", "storage", "percentage", 95, "Storage emergency threshold", "آستانه اضطراری فضا", unit="percent", minimum=3, maximum=100),
    _setting("cleanup.interval", "cleanup", "duration", 300, "Cleanup interval", "فاصله پاک‌سازی", unit="seconds", minimum=30, maximum=86400),
    _setting("cleanup.batch_size", "cleanup", "integer", 100, "Cleanup batch size", "اندازه دسته پاک‌سازی", minimum=1, maximum=5000),
    _setting("public.enabled", "public", "boolean", True, "Public sharing", "اشتراک عمومی"),
    _setting("public.auto_approve", "public", "boolean", False, "Public auto approval", "تأیید خودکار عمومی", permission="public.publish"),
    _setting("public.report_threshold", "public", "integer", 5, "Public report threshold", "آستانه گزارش عمومی", minimum=1, maximum=1000),
    _setting("broadcast.batch_size", "broadcast", "integer", 25, "Broadcast batch size", "اندازه دسته همگانی", minimum=1, maximum=100),
    _setting("broadcast.rate_per_second", "broadcast", "decimal", 20, "Broadcast send rate", "نرخ ارسال همگانی", unit="per_second", minimum="0.1", maximum=30),
    _setting("support.open_ticket_limit", "support", "integer", 3, "Open ticket limit", "حد تیکت باز", minimum=1, maximum=100),
    _setting("telegram.api_mode", "telegram", "enum", "local", "Telegram API mode", "حالت API تلگرام", allowed=("local", "official"), reload_type="restart_required"),
    _setting("telegram.cloud_upload_limit", "telegram", "bytes", 50 * 1024**2, "Cloud upload limit", "حد آپلود ابری", unit="bytes", minimum=1024**2, maximum=50 * 1024**2),
    _setting("telegram.local_upload_limit", "telegram", "bytes", 2 * 1024**3, "Local upload limit", "حد آپلود محلی", unit="bytes", minimum=1024**2, maximum=20 * 1024**3),
)


PROFILES: tuple[SettingsProfileDefinition, ...] = (
    SettingsProfileDefinition("economic", "اقتصادی", "Economic", "مصرف منابع کمتر", "Lower resource usage", {"files.concurrent_jobs": 2, "queue.dispatch_batch": 20, "broadcast.batch_size": 10}),
    SettingsProfileDefinition("balanced", "متعادل", "Balanced", "پیش‌فرض متعادل", "Balanced defaults", {"files.concurrent_jobs": 4, "queue.dispatch_batch": 50, "broadcast.batch_size": 25}),
    SettingsProfileDefinition("high_performance", "کارایی بالا", "High Performance", "ظرفیت پردازش بیشتر", "Higher processing capacity", {"files.concurrent_jobs": 16, "queue.dispatch_batch": 200, "broadcast.batch_size": 50}),
    SettingsProfileDefinition("strict", "سخت‌گیرانه", "Strict", "کنترل امنیتی محافظه‌کارانه", "Conservative security policy", {"security.scan_required": True, "security.url_max_redirects": 2, "public.auto_approve": False}),
    SettingsProfileDefinition("under_attack", "تحت حمله", "Under Attack", "کاهش سطح حمله و بار", "Reduced attack surface and load", {"public.enabled": False, "broadcast.rate_per_second": 2, "security.url_max_redirects": 0}),
    SettingsProfileDefinition("maintenance", "نگهداری", "Maintenance", "توقف پذیرش کار جدید", "Stops new job admission", {"system.maintenance": True, "admission.enabled": False}),
    SettingsProfileDefinition("weak_server", "سرور ضعیف", "Weak Server", "مناسب منابع محدود", "For constrained resources", {"files.concurrent_jobs": 1, "queue.dispatch_batch": 10, "cleanup.batch_size": 25}),
    SettingsProfileDefinition("strong_server", "سرور قدرتمند", "Strong Server", "مناسب منابع بالا", "For ample resources", {"files.concurrent_jobs": 32, "queue.dispatch_batch": 500, "cleanup.batch_size": 500}),
    SettingsProfileDefinition("custom", "سفارشی", "Custom", "نمایه قابل تنظیم مدیر", "Administrator-defined profile", {}),
)


def validate_catalogs() -> None:
    permission_codes = [item.code for item in PERMISSIONS]
    setting_keys = [item.key for item in SETTINGS]
    role_codes = [item.code for item in ROLES]
    profile_codes = [item.code for item in PROFILES]
    for label, values in (
        ("permission", permission_codes),
        ("setting", setting_keys),
        ("role", role_codes),
        ("profile", profile_codes),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label} catalog entry")
    known_permissions = set(permission_codes)
    for role in ROLES:
        unknown = set(role.permissions) - known_permissions
        if unknown:
            raise ValueError(f"role {role.code} contains unknown permissions: {sorted(unknown)}")
    known_settings = set(setting_keys)
    for profile in PROFILES:
        unknown = set(profile.values) - known_settings
        if unknown:
            raise ValueError(f"profile {profile.code} contains unknown settings: {sorted(unknown)}")


validate_catalogs()
