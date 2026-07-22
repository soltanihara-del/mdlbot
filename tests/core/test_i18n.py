from pathlib import Path
import shutil

import pytest

from app.core.errors import LocalizationError
from app.core.i18n import LocalizationService, RESOURCE_FILES


ROOT = Path(__file__).parents[2] / "locales"


def test_locales_have_exact_contract_and_escape_arguments() -> None:
    service = LocalizationService(ROOT)
    service.load()
    assert service.ready
    assert service.format("en", "welcome", name="<script>") == "Welcome, &lt;script&gt;."
    assert service.format("fa", "error-file-too-large", limit="2 GB").endswith("است.")


def test_all_required_resources_exist() -> None:
    for locale in ("fa", "en"):
        assert {path.name for path in (ROOT / locale).glob("*.ftl")} == set(RESOURCE_FILES)


def test_missing_translation_key_fails_startup(tmp_path) -> None:
    root = tmp_path / "locales"
    shutil.copytree(ROOT, root)
    path = root / "en" / "public.ftl"
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace("public-watch = Watch online\n", ""), encoding="utf-8")
    with pytest.raises(LocalizationError):
        LocalizationService(root).load()


def test_forbidden_translation_markup_fails_startup(tmp_path) -> None:
    root = tmp_path / "locales"
    shutil.copytree(ROOT, root)
    path = root / "fa" / "messages.ftl"
    path.write_text(path.read_text(encoding="utf-8") + "bad-tag = <a href='x'>bad</a>\n", encoding="utf-8")
    with pytest.raises(LocalizationError):
        LocalizationService(root).load()
