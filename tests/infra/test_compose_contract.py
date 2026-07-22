from __future__ import annotations

from pathlib import Path
import re
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
COMPOSE = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
PRODUCTION = yaml.safe_load(
    (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
)

REQUIRED_SERVICES = {
    "nginx",
    "bot",
    "api",
    "dispatcher",
    "external-download-worker",
    "telegram-download-worker",
    "telegram-upload-worker",
    "media-worker",
    "cleanup-worker",
    "broadcast-worker",
    "scheduler",
    "usage-collector",
    "postgres",
    "redis",
    "telegram-bot-api",
    "clamav",
    "backup-service",
    "monitoring",
}

REQUIRED_NETWORKS = {
    "public_network",
    "application_network",
    "database_network",
    "telegram_network",
    "media_network",
    "scanner_network",
    "external_download_network",
}


def service_networks(service: dict[str, object]) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, list):
        return set(networks)
    return set(networks)


def test_required_services_networks_volumes_and_secrets_exist() -> None:
    assert REQUIRED_SERVICES <= set(SERVICES)
    assert REQUIRED_NETWORKS == set(COMPOSE["networks"])
    assert len(COMPOSE["volumes"]) >= 10
    assert len(COMPOSE["secrets"]) >= 10


def test_only_nginx_publishes_host_ports() -> None:
    publishers = {name for name, service in SERVICES.items() if service.get("ports")}
    assert publishers == {"nginx"}
    assert service_networks(SERVICES["nginx"]) == {
        "public_network",
        "application_network",
    }
    public_members = {
        name
        for name, service in SERVICES.items()
        if "public_network" in service_networks(service)
    }
    assert public_members == {"nginx"}


def test_untrusted_workers_have_the_expected_network_boundaries() -> None:
    assert service_networks(SERVICES["external-download-worker"]) == {
        "external_download_network",
        "scanner_network",
    }
    assert "database_network" not in service_networks(
        SERVICES["external-download-worker"]
    )
    assert "telegram_network" not in service_networks(
        SERVICES["external-download-worker"]
    )

    media_networks = service_networks(SERVICES["media-worker"])
    assert media_networks == {
        "application_network",
        "media_network",
        "scanner_network",
    }
    assert COMPOSE["networks"]["media_network"]["internal"] is True
    assert COMPOSE["networks"]["scanner_network"]["internal"] is True


def test_every_service_is_hardened_and_resource_bounded() -> None:
    for name, service in SERVICES.items():
        assert service.get("privileged") is not True, name
        assert service.get("network_mode") != "host", name
        assert service.get("read_only") is True, name
        assert "ALL" in service.get("cap_drop", []), name
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert isinstance(service.get("pids_limit"), int), name
        assert service.get("mem_limit"), name
        assert service.get("cpus"), name
        assert service.get("logging", {}).get("options", {}).get("max-size"), name
        user = str(service.get("user", ""))
        assert user and user not in {"0", "0:0", "root", "root:root"}, name


def test_production_overlay_assigns_workload_apparmor_profiles() -> None:
    expected = {
        "nginx",
        "bot",
        "api",
        "dispatcher",
        "external-download-worker",
        "telegram-download-worker",
        "telegram-upload-worker",
        "media-worker",
        "cleanup-worker",
        "broadcast-worker",
        "scheduler",
        "usage-collector",
        "backup-service",
        "migrate",
        "bootstrap",
    }
    assert set(PRODUCTION["services"]) == expected
    for name, service in PRODUCTION["services"].items():
        security = service["security_opt"]
        assert "no-new-privileges:true" in security, name
        assert any(item.startswith("apparmor=mdlbot-") for item in security), name


def test_images_and_build_arguments_are_version_pinned() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert ":latest" not in text
    assert "TELEGRAM_BOT_API_COMMIT: adfd7f6a8e990272851777eeb3ae0def4216f161" in text

    dockerfiles = [ROOT / "Dockerfile", *sorted((ROOT / "docker").glob("*.Dockerfile"))]
    for dockerfile in dockerfiles:
        source = dockerfile.read_text(encoding="utf-8")
        assert ":latest" not in source, dockerfile
        build_stages: set[str] = set()
        for match in re.finditer(
            r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?$", source, re.MULTILINE
        ):
            image, stage = match.groups()
            assert "$" in image or ":" in image or image in build_stages, (
                dockerfile,
                image,
            )
            if stage:
                build_stages.add(stage)


def test_secret_values_are_file_mounted_not_embedded_in_environment() -> None:
    for secret_name, definition in COMPOSE["secrets"].items():
        assert definition["file"] == f"./secrets/{secret_name}"

    forbidden_environment_keys = re.compile(
        r"(^|_)(PASSWORD|TOKEN|SECRET|API_HASH|SIGNING_KEY|ENCRYPTION_KEY)$"
    )
    for service_name, service in SERVICES.items():
        environment = service.get("environment", {})
        if isinstance(environment, list):
            keys = {entry.split("=", 1)[0] for entry in environment}
        else:
            keys = set(environment)
        embedded = {key for key in keys if forbidden_environment_keys.search(key)}
        assert not embedded, service_name


def test_internal_services_do_not_publish_ports() -> None:
    for name in ("postgres", "redis", "telegram-bot-api", "clamav", "monitoring"):
        assert "ports" not in SERVICES[name], name


def test_no_docker_socket_or_broad_host_mount_is_present() -> None:
    allowed_bind_sources = {
        "./runtime/tls",
        "./docker/monitoring/prometheus.yml",
    }
    for name, service in SERVICES.items():
        for volume in service.get("volumes", []):
            if isinstance(volume, dict) and volume.get("type") == "bind":
                assert volume["source"] in allowed_bind_sources, name
            if isinstance(volume, str) and volume.startswith("./"):
                assert volume.split(":", 1)[0] in allowed_bind_sources, name
            assert "docker.sock" not in str(volume), name


def test_secret_values_are_not_forwarded_as_process_arguments() -> None:
    for script in (ROOT / "docker").glob("**/*.sh"):
        source = script.read_text(encoding="utf-8")
        assert not re.search(r"--(?:password|token|api-hash)=", source), script
    postgres_init = (
        ROOT / "docker/postgres/initdb/00-security-roles.sh"
    ).read_text(encoding="utf-8")
    assert "--set=app_password" not in postgres_init
    assert "--set=backup_password" not in postgres_init


def test_shell_entrypoints_have_valid_posix_shell_syntax() -> None:
    scripts = sorted((ROOT / "docker").glob("**/*.sh"))
    assert scripts
    for script in scripts:
        result = subprocess.run(
            ["sh", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_nginx_delivery_locations_are_internal_and_range_is_bounded() -> None:
    nginx = (ROOT / "docker/nginx/site.conf.template").read_text(encoding="utf-8")
    main = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    assert nginx.count("internal;") == 3
    assert "max_ranges 1;" in main
    assert "access-$log_day.json" in main
    assert "server_name _;" in nginx
    assert "return 444;" in nginx
    assert "$request_method != POST" in nginx
    assert "$content_type !~*" in nginx
