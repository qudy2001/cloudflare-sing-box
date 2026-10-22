ARG SING_BOX_VERSION=v1.14.3
FROM ghcr.io/sagernet/sing-box:${SING_BOX_VERSION}

# The image intentionally contains no tunnel token, proxy UUID, or client rules.
# Mount server.json at runtime with Docker Compose.
