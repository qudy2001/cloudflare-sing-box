# Cloudflare Tunnel + sing-box（先配置 Mac）

[English](README.md)

本仓库提供部署模板。Mac 客户端会从你自行指定的 URL 下载 GFW 规则集；仓库没有预设规则集地址。

## 准备条件

- 一台位于目标出口地区的 Docker 主机。代理流量最终从这台主机访问互联网。
- 一个由 Cloudflare 管理的域名，以及已运行的 Cloudflare Tunnel。
- macOS 13 或更新版本的 SFM。M1 Mac 请从 [sing-box Releases](https://github.com/SagerNet/sing-box/releases) 下载 `SFM-*-Apple.pkg`。

## 服务端部署

1. 复制 `server.example.json` 为 `server.json`，复制 `mac.example.json` 为 `mac.json`。生成一个 UUID（macOS 可运行 `uuidgen`，Linux 可运行 `cat /proc/sys/kernel/random/uuid`），把两个文件中的 `REPLACE_WITH_SAME_UUID_AS_MAC_CLIENT` 替换成同一个 UUID。不要公开这个 UUID。
2. 在 Docker 主机上复制 `.env.example` 为 `.env`。将 `TUNNEL_NETWORK` 设为现有 `cloudflared` 容器所在的 Docker 网络名称。此 Compose 只启动 sing-box，不会另起 Tunnel 连接器。
3. 在 Cloudflare 的 Tunnel 管理页面，为现有 Tunnel 手动添加你选定主机名的公开应用路由，服务地址填 `http://sing-box:10000`。客户端与 Cloudflare 边缘之间使用该主机名的 HTTPS 证书。该路由不要开启需要浏览器登录的 Cloudflare Access 验证；SFM 无法在 VMess WebSocket 连接中完成这种登录。
4. 在 Docker 主机上运行 `docker compose config` 检查配置，再运行 `docker compose up -d`。Compose 不向主机发布端口；`cloudflared` 与 sing-box 通过同一 Docker 网络通信。
5. 运行 `docker compose ps` 和 `docker compose logs --tail=100 sing-box` 检查容器。Tunnel 显示在线只说明它与 Cloudflare 已连接，还需要单独确认应用路由能到达 sing-box。

## GitHub 镜像

`Dockerfile` 基于官方 sing-box `v1.14.3` 镜像，不包含 Tunnel token、UUID 或客户端规则。向 `main` 分支推送时，GitHub Actions 会构建并发布 `linux/amd64`、`linux/arm64` 镜像：

```text
ghcr.io/qudy2001/cloudflare-sing-box:latest
```

推送 `v*` 标签或手动运行工作流可发布带版本号的标签。镜像目前已可匿名拉取。`.env.example` 已指定本仓库的镜像地址。不要将填写了真实 UUID 的 `.env`、`server.json` 或 `mac.json` 提交到公开仓库。

## 可选：内网管理页面

独立镜像 `ghcr.io/qudy2001/cloudflare-sing-box-manager:latest` 在同一个容器中运行 sing-box 和管理页面。代理在容器内固定监听 **10000**，管理页面监听 **8080**。页面可新增、删除或重置用户 UUID，并修改 WebSocket 路径和日志级别。每次保存都会先运行 `sing-box check`，通过后才重启代理进程。首次启动会导入现有的 `server.json`，之后的设置保存在 Docker 命名卷中。

1. 按前文准备含真实 UUID 的 `server.json`。复制 `.env.manager.example` 为 `.env.manager`，填写 `TUNNEL_NETWORK`。
2. 管理端口默认**不映射到宿主机**。由你在 `compose.manager.yaml` 的 `sing-box` 服务下添加端口映射，例如 `ports: ["192.168.1.10:8080:8080"]`，把 IP 换成 Docker 主机实际内网地址。
3. 运行 `docker compose down` 停止原服务，再运行 `docker compose --env-file .env.manager -f compose.manager.yaml up -d` 启动管理版。现有 Cloudflare route 仍指向 `http://sing-box:10000`。然后从内网打开 Docker 主机的管理地址。

管理页面按你的要求**不设登录密码**。只应映射到可信内网或受保护的私有访问路径，不要为 8080 创建 Cloudflare 公网路由。修改 WebSocket 路径或用户 UUID 后，还要更新对应客户端。重建容器时保留命名卷；删除命名卷会重置管理数据。

## Mac 客户端

1. 在复制出的 `mac.json` 中，将 `server` 和 `tls.server_name` 两处的 `REPLACE_WITH_YOUR_CLOUDFLARE_HOSTNAME` 替换为 Tunnel 路由中配置的主机名。
2. 将 `REPLACE_WITH_YOUR_GFWLIST_SRS_URL` 替换为你选择的 **sing-box 二进制规则集（`.srs`）HTTPS 地址**。普通 GFWList 文本文件不能直接填入这个配置。
3. 在 SFM 中导入本地 `mac.json` 配置，启动连接，并允许 macOS 的 VPN／网络扩展权限。连接成功后，如需集中管理，也可以让 SFM 从私有 HTTPS 地址下载完整配置；不要把含 UUID 的配置放在公开 URL。
4. 当前规则顺序是：识别协议并接管 DNS、私有地址直连、命中 GFW 规则集的流量走 `proxy`、其余流量直连。远程规则集每天检查更新；首次成功下载后会保存在本地缓存。

## 验证

- 确认 Cloudflare 主机名呈现有效的边缘证书，WebSocket 请求能到达 sing-box。
- 访问规则集内的域名，确认出口 IP 是 Docker 主机的出口；访问规则集外的域名，确认由 Mac 直连。
- 暂时断开 Tunnel：应只有命中代理规则的目标无法访问，直连目标仍可访问。
- 如有问题，查看 SFM 日志中的规则集下载、DNS 和路由错误。首次启动需要能访问规则集 URL；成功缓存后，短暂的更新失败不一定影响启动。

## 说明

Cloudflare Tunnel 负责把客户端流量送到代理服务，最终出口 IP 仍是 Docker 主机的出口 IP。客户端到 Cloudflare 边缘使用 HTTPS；本方案的 `cloudflared` 到 sing-box 则是在同一 Docker 网络内使用 HTTP。Tunnel 支持 WebSocket，但网络或服务变化时，长连接仍可能中断。
