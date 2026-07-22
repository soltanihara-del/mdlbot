from uuid import uuid4

from app.core.permissions import AuthorizationRequest, ScopeEvaluator
from app.db.models.admin import AdminScope


def scope(scope_type: str, constraints: dict) -> AdminScope:
    return AdminScope(admin_id=uuid4(), scope_type=scope_type, constraints_json=constraints)


def test_scope_evaluator_denies_mutation_for_read_only() -> None:
    request = AuthorizationRequest(admin_id=uuid4(), permission="users.manage", mutating=True)
    assert ScopeEvaluator.evaluate(request, [scope("read_only", {})]) == (
        False,
        "scope_read_only",
    )


def test_scope_evaluator_applies_target_and_numeric_limits() -> None:
    allowed_user = uuid4()
    request = AuthorizationRequest(
        admin_id=uuid4(),
        permission="users.ban",
        target_user_id=allowed_user,
        ban_seconds=7200,
        mutating=True,
    )
    scopes = [
        scope("users", {"allowed": [str(allowed_user)]}),
        scope("ban_limit", {"maximum_seconds": 3600}),
    ]
    assert ScopeEvaluator.evaluate(request, scopes) == (False, "scope_ban_limit")


def test_scope_evaluator_allows_matching_constraints() -> None:
    request = AuthorizationRequest(
        admin_id=uuid4(),
        permission="broadcast.send",
        recipient_count=100,
        mutating=True,
    )
    assert ScopeEvaluator.evaluate(
        request,
        [scope("recipient_limit", {"maximum": 100})],
    ) == (True, "scope_allowed")
