from app.core.logging import REDACTED, redact_value


def test_recursive_log_redaction() -> None:
    event = {
        "database_url": "postgresql://user:password@db/app",
        "nested": {"bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
        "message": "failed redis://user:password@cache/0",
    }
    redacted = redact_value(event)
    assert redacted["database_url"] == REDACTED
    assert redacted["nested"]["bot_token"] == REDACTED
    assert "user:password" not in redacted["message"]
