"""Strict Persian/English Fluent loading and safe rendering."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from fluent.runtime import FluentBundle, FluentResource
from fluent.syntax import FluentParser
from fluent.syntax.ast import Junk, Message

from app.core.errors import LocalizationError


LOCALES = ("fa", "en")
RESOURCE_FILES = ("messages.ftl", "buttons.ftl", "admin.ftl", "errors.ftl", "web.ftl", "public.ftl")
TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>")
ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre"}


def _walk_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child))
    return found


@dataclass(frozen=True, slots=True)
class MessageContract:
    variables: frozenset[str]
    select_variants: frozenset[str]


def _message_contract(message: Message) -> MessageContract:
    tree = message.to_json()
    nodes = _walk_json(tree)
    variables = {
        node["id"]["name"]
        for node in nodes
        if node.get("type") == "VariableReference" and isinstance(node.get("id"), dict)
    }
    variants = {
        json.dumps(node.get("key"), sort_keys=True)
        for node in nodes
        if node.get("type") == "Variant"
    }
    return MessageContract(frozenset(variables), frozenset(variants))


def _validate_markup(source: str, *, resource: str) -> None:
    for match in TAG_RE.finditer(source):
        tag = match.group(2).lower()
        if tag not in ALLOWED_TAGS or match.group(0).strip().lower() not in {
            f"<{tag}>",
            f"</{tag}>",
        }:
            raise LocalizationError(
                "translation contains forbidden markup",
                context={"resource": resource, "tag": tag},
            )


class LocalizationService:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._bundles: dict[str, FluentBundle] = {}
        self._contracts: dict[str, dict[str, MessageContract]] = {}

    @property
    def ready(self) -> bool:
        return set(self._bundles) == set(LOCALES)

    def load(self) -> None:
        parser = FluentParser(with_spans=False)
        sources: dict[str, dict[str, str]] = {locale: {} for locale in LOCALES}
        contracts: dict[str, dict[str, MessageContract]] = {locale: {} for locale in LOCALES}
        bundles = {locale: FluentBundle([locale], use_isolating=False) for locale in LOCALES}

        for locale in LOCALES:
            seen: set[str] = set()
            for filename in RESOURCE_FILES:
                path = self._root / locale / filename
                try:
                    source = path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise LocalizationError(
                        "translation resource is missing",
                        context={"locale": locale, "file": filename},
                    ) from exc
                _validate_markup(source, resource=str(path))
                resource_ast = parser.parse(source)
                if any(isinstance(entry, Junk) for entry in resource_ast.body):
                    raise LocalizationError(
                        "translation resource is malformed",
                        context={"locale": locale, "file": filename},
                    )
                file_contracts: dict[str, MessageContract] = {}
                for entry in resource_ast.body:
                    if not isinstance(entry, Message):
                        continue
                    key = entry.id.name
                    if entry.value is None or not entry.value.elements:
                        raise LocalizationError("translation message is empty", context={"key": key})
                    if key in seen:
                        raise LocalizationError("duplicate translation key", context={"key": key})
                    seen.add(key)
                    file_contracts[key] = _message_contract(entry)
                sources[locale][filename] = source
                contracts[locale][filename] = file_contracts  # type: ignore[assignment]
                errors = bundles[locale].add_resource(FluentResource(source))
                if errors:
                    raise LocalizationError(
                        "Fluent rejected a translation resource",
                        context={"locale": locale, "file": filename, "errors": len(errors)},
                    )

        for filename in RESOURCE_FILES:
            fa = contracts["fa"][filename]  # type: ignore[index]
            en = contracts["en"][filename]  # type: ignore[index]
            if set(fa) != set(en):
                raise LocalizationError(
                    "translation key parity failed",
                    context={"file": filename, "fa_only": sorted(set(fa) - set(en)), "en_only": sorted(set(en) - set(fa))},
                )
            for key in fa:
                if fa[key] != en[key]:
                    raise LocalizationError(
                        "translation variable/select parity failed",
                        context={"file": filename, "key": key},
                    )
                if filename == "buttons.ftl":
                    for locale in LOCALES:
                        message = bundles[locale].get_message(key)
                        rendered, errors = bundles[locale].format_pattern(message.value, {})
                        if not fa[key].variables and (errors or len(str(rendered)) > 64):
                            raise LocalizationError(
                                "button label exceeds Telegram limit",
                                context={"locale": locale, "key": key},
                            )

        self._bundles = bundles
        self._contracts = contracts  # type: ignore[assignment]

    def format(self, locale: str, key: str, **arguments: Any) -> str:
        if locale not in LOCALES:
            raise LocalizationError("unsupported locale", context={"locale": locale})
        bundle = self._bundles.get(locale)
        if bundle is None:
            raise LocalizationError("localization service is not loaded")
        message = bundle.get_message(key)
        if message is None or message.value is None:
            raise LocalizationError("translation key is missing", context={"locale": locale, "key": key})
        safe_arguments = {
            name: escape(str(value), quote=True) if isinstance(value, str) else value
            for name, value in arguments.items()
        }
        rendered, errors = bundle.format_pattern(message.value, safe_arguments)
        if errors:
            raise LocalizationError(
                "translation formatting failed",
                context={"locale": locale, "key": key, "errors": len(errors)},
            )
        return str(rendered)
