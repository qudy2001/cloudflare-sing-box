# Cloudflare Tunnel + sing-box (Mac first)

[简体中文说明](README.zh-CN.md)

This directory is a deployment template. The Mac downloads the GFW rule set from the URL you choose; this repository does not set that URL.

## Requirements

- A Docker host in the country where you want traffic to exit.
- A Cloudflare-managed domain and a remotely managed Tunnel.
- SFM for macOS 13 or later. For an M1 Mac, download `SFM-*-Apple.pkg` from [sing-box releases](https://github.com/SagerNet/sing-box/releases).

## Server setup

1. Copy `server.example.json` to `server.json` and `mac.example.json` to `mac.json`. Generate a fresh UUID (`uuidgen` on macOS or `cat /proc/sys/kernel/random/uuid` on Linux). Replace `REPLACE_WITH_SAME_UUID_AS_MAC_CLIENT` in both files with the same value. Keep this value private.
2. Copy `.env.example` to `.env` on the Docker host. Set `TUNNEL_NETWORK` to the existing Docker network shared with your `cloudflared` container. The Compose project starts only sing-box and joins that network. It does not start a second Tunnel connector.
3. In Cloudflare > Networking > Tunnels, manually add a **Published application** route for `users.braineedash.co.uk` on the existing Tunnel. Set the service URL to `http://sing-box:10000`. Use the active Cloudflare edge certificate. Do not enable browser-based Access login for this route, since SFM cannot complete that login inside the VMess WebSocket connection.
4. Run `docker compose config` to inspect the resolved Compose file, then `docker compose up -d` on the Docker host. No host port is published; the existing `cloudflared` connector and sing-box communicate through their shared Docker network.
5. Check `docker compose ps` and `docker compose logs --tail=100 sing-box`. The Tunnel being healthy only proves its Cloudflare connection; also check the application route.

## GitHub Container Registry

The Dockerfile layers on the official sing-box 1.14.3 image and includes no credentials or configuration. A push to `main` publishes a multi-architecture image to `ghcr.io/qudy2001/cloudflare-sing-box:latest` using this repository's `GITHUB_TOKEN`. A `v*` tag push or manual workflow run publishes a versioned tag. In GitHub Packages, check the package visibility and set it to **Public** if it is Private. Keep `.env`, `server.json` with a real UUID, and `mac.json` with a real UUID out of public GitHub repositories.

## Mac setup

1. The copied `mac.json` is already set to connect to `users.braineedash.co.uk`.
2. Replace `REPLACE_WITH_YOUR_GFWLIST_SRS_URL` with your chosen **sing-box binary rule-set (`.srs`) HTTPS URL**. A plain GFWList text file is not accepted by this configuration. Leave the URL for the user to choose; this template has no default.
3. Import `mac.json` as a local profile in SFM, start it, and allow the macOS VPN/network extension permission. After it works, SFM may instead load a full profile from a private HTTPS URL if you want centrally managed config. Keep the UUID out of public URLs and files.
4. The rule order is: sniff and DNS handling, private addresses direct, GFW rule-set through `proxy`, everything else direct. The remote rule-set refreshes daily and is cached after its first successful download.

## Checks

- Confirm the Cloudflare hostname presents a valid edge certificate and WebSocket requests reach sing-box.
- Confirm a domain in your selected GFW rule-set exits through the Docker host, while a domain absent from the list exits directly from the Mac.
- Disconnect the Tunnel: matching proxy destinations should fail; direct destinations should continue working.
- Check SFM logs for rule-set download, DNS, and route errors. The first start needs the rule-set URL to be reachable; after that, cache permits a temporary update failure.

## Notes

Cloudflare Tunnel changes the path to the proxy service, not the final egress IP. The Docker host is the egress. Cloudflare's free Universal SSL covers proxied first-level subdomains, while the `cloudflared` to sing-box connection here is local HTTP inside Docker. Cloudflare Tunnel supports WebSocket, but long-lived connections can still drop during network or service changes.
