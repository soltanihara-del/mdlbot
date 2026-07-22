from decimal import Decimal

import pytest

from app.core.errors import SettingsValidationError
from app.core.settings import parse_setting_value, validate_cross_setting_invariants
from app.db.models.admin import Setting


def setting(value_type: str, **values) -> Setting:
    defaults = {
        "key": "test.value",
        "value_type": value_type,
        "minimum": None,
        "maximum": None,
        "allowed_values": None,
    }
    defaults.update(values)
    return Setting(**defaults)


@pytest.mark.parametrize(
    ("value_type", "raw", "canonical"),
    [
        ("bytes", "2GB", 2 * 1024**3),
        ("duration", "1h 30m", 5400),
        ("bitrate", "10Mbps", 10_000_000),
        ("boolean", "off", False),
        ("integer", "42", 42),
        ("decimal", "0.25", 0.25),
    ],
)
def test_typed_setting_parser(value_type, raw, canonical) -> None:
    assert parse_setting_value(setting(value_type), raw) == canonical


def test_setting_parser_enforces_range_and_enum() -> None:
    with pytest.raises(SettingsValidationError):
        parse_setting_value(setting("integer", minimum=Decimal("1"), maximum=Decimal("5")), 8)
    with pytest.raises(SettingsValidationError):
        parse_setting_value(setting("enum", allowed_values=["local", "cloud"]), "other")


def test_cross_setting_invariants_fail_closed() -> None:
    with pytest.raises(SettingsValidationError):
        validate_cross_setting_invariants(
            {
                "storage.warning_percent": 90,
                "storage.stop_percent": 80,
                "storage.emergency_percent": 95,
            }
        )
    with pytest.raises(SettingsValidationError):
        validate_cross_setting_invariants(
            {
                "telegram.api_mode": "official",
                "telegram.cloud_upload_limit": 50 * 1024**2,
                "files.max_size": 51 * 1024**2,
            }
        )
