from app.core.catalogs import PLANS, PERMISSIONS, PROFILES, ROLES, SETTINGS, validate_catalogs


def test_catalogs_are_unique_and_referentially_complete() -> None:
    validate_catalogs()
    assert len(PERMISSIONS) >= 30
    assert {role.code for role in ROLES} >= {"super_admin", "viewer", "security_auditor"}
    assert {profile.code for profile in PROFILES} == {
        "economic", "balanced", "high_performance", "strict", "under_attack",
        "maintenance", "weak_server", "strong_server", "custom",
    }
    assert all(item.name_fa and item.name_en for item in (*PERMISSIONS, *SETTINGS))
    assert all(not item.key.endswith(("password", "token", "secret")) for item in SETTINGS)
    assert {plan.code for plan in PLANS} == {"normal", "vip"}
    assert all(plan.concurrent_jobs > 0 and plan.max_file_size > 0 for plan in PLANS)


def test_super_admin_catalog_contains_every_permission() -> None:
    super_admin = next(role for role in ROLES if role.is_super_admin)
    assert set(super_admin.permissions) == {permission.code for permission in PERMISSIONS}
