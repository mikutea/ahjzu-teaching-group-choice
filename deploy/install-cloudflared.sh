#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ahjzu-teaching-group-choice}"
TOKEN_FILE="${TOKEN_FILE:-/etc/cloudflared/teaching-choice.token}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 权限运行此脚本。" >&2
  exit 1
fi

if [[ ! -s "${TOKEN_FILE}" ]]; then
  echo "未找到 Tunnel token 文件：${TOKEN_FILE}" >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/deploy/cloudflared.service" ]]; then
  echo "未找到 ${APP_DIR}/deploy/cloudflared.service" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl
install -d -m 0755 /usr/share/keyrings /etc/cloudflared
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared noble main" \
  > /etc/apt/sources.list.d/cloudflared.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared

if ! id cloudflared >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/cloudflared --create-home \
    --shell /usr/sbin/nologin cloudflared
fi

chown root:cloudflared "${TOKEN_FILE}"
chmod 0640 "${TOKEN_FILE}"
install -m 0644 "${APP_DIR}/deploy/cloudflared.service" \
  /etc/systemd/system/cloudflared.service

systemctl daemon-reload
systemctl enable --now cloudflared.service
systemctl is-active --quiet cloudflared.service
cloudflared --version
