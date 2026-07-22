# Container security profiles

Docker's default seccomp allow-list remains enabled for every service. The
Compose files never request `seccomp=unconfined`, privileged mode, host
networking, or the Docker socket. The AppArmor overlay adds workload-specific
filesystem and capability restrictions on Linux hosts that support AppArmor.

Load the profiles as root before using the security overlay:

```bash
apparmor_parser -r docker/security/apparmor/mdlbot-app
apparmor_parser -r docker/security/apparmor/mdlbot-external-download
apparmor_parser -r docker/security/apparmor/mdlbot-media
apparmor_parser -r docker/security/apparmor/mdlbot-nginx
```

Validate that all profiles are loaded:

```bash
aa-status | grep -E 'mdlbot-(app|external-download|media|nginx)'
```

Start the recommended Local Bot API deployment with the hardened overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml \
  --profile local-bot-api up -d
```

The host-level egress policy for `172.29.60.0/24` is intentionally owned by
the Stage 10 installer. AppArmor cannot express destination-IP allow/deny
rules; nftables/DOCKER-USER must block private, loopback, link-local, metadata,
Docker, and host networks while permitting DNS and outbound HTTP(S).
