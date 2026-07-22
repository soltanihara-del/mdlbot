"""Process entrypoint for implemented services and management operations."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import os
import sys
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from app.core.bootstrap import ensure_super_admin, seed_catalogs
from app.core.config import load_settings
from app.core.errors import ApplicationError, StageBoundaryError
from app.core.logging import configure_logging, get_logger
from app.db.session import Database
from app.background import heartbeat_path, run_background_service


IMPLEMENTED_SERVICES = {
    "api",
    "bot",
    "dispatcher",
    "external-download-worker",
    "telegram-download-worker",
    "telegram-upload-worker",
}


async def _bootstrap() -> None:
    settings = load_settings("bootstrap")
    settings.validate_dependencies(redis=False)
    database = Database(settings)
    await database.start()
    try:
        async with database.transaction() as session:
            await seed_catalogs(session)
            telegram_id = os.environ.get("INITIAL_SUPER_ADMIN_TELEGRAM_ID")
            if telegram_id:
                await ensure_super_admin(
                    session,
                    telegram_user_id=int(telegram_id),
                    language_code=os.environ.get("INITIAL_SUPER_ADMIN_LANGUAGE", "fa"),
                )
    finally:
        await database.close()


def _run(service: str) -> None:
    if service not in IMPLEMENTED_SERVICES:
        raise StageBoundaryError(
            "service implementation belongs to a later stage",
            context={"service": service, "implemented": sorted(IMPLEMENTED_SERVICES)},
        )
    settings = load_settings(service)
    if service not in {"api", "bot"}:
        asyncio.run(run_background_service(service, settings))
        return
    app_path = "app.api.app:application" if service == "api" else "app.bot.server:application"
    port = settings.api_port if service == "api" else settings.bot_internal_port
    uvicorn.run(
        app_path,
        host=settings.api_host if service == "api" else settings.bot_internal_host,
        port=port,
        log_config=None,
        proxy_headers=False,
        server_header=False,
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
    )


def _healthcheck(service: str) -> None:
    if service not in IMPLEMENTED_SERVICES:
        raise StageBoundaryError("service is not implemented", context={"service": service})
    settings = load_settings(service)
    if service not in {"api", "bot"}:
        path = heartbeat_path(service)
        if not path.is_file() or datetime.now().timestamp() - path.stat().st_mtime > 60:
            raise RuntimeError("background service heartbeat is stale")
        return
    try:
        port = settings.api_port if service == "api" else settings.bot_internal_port
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=4) as response:
            if response.status != 200:
                raise RuntimeError(f"unhealthy HTTP status: {response.status}")
    except (OSError, URLError) as exc:
        raise RuntimeError("service liveness check failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "healthcheck"):
        child = subparsers.add_parser(command)
        child.add_argument("service")
    subparsers.add_parser("bootstrap")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    service = getattr(arguments, "service", "bootstrap")
    settings = load_settings(service)
    configure_logging(level=settings.log_level, output_format=settings.log_format)
    log = get_logger("runtime")
    try:
        if arguments.command == "run":
            _run(arguments.service)
        elif arguments.command == "healthcheck":
            _healthcheck(arguments.service)
        else:
            asyncio.run(_bootstrap())
        return 0
    except (ApplicationError, RuntimeError, ValueError) as exc:
        log.error(
            "runtime_failed",
            command=arguments.command,
            service=service,
            error_code=getattr(exc, "code", "runtime_error"),
            context=getattr(exc, "context", {}),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
