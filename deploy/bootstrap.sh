#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行此脚本" >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/ahjzu-teaching-group-choice}"
PUBLIC_URL="${PUBLIC_URL:-}"

if [[ ! -f "${APP_DIR}/docker-compose.yml" ]]; then
  echo "未找到 ${APP_DIR}/docker-compose.yml" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 curl openssl
systemctl enable --now docker

cd "${APP_DIR}"
mkdir -p data
chown -R 10001:10001 data
chmod 750 data

if [[ -z "${PUBLIC_URL}" ]]; then
  PRIMARY_IP="$(hostname -I | awk '{print $1}')"
  PUBLIC_URL="http://${PRIMARY_IP}"
fi

if [[ ! -f .env ]]; then
  APP_SECRET_VALUE="$(openssl rand -hex 32)"
  ADMIN_PASSWORD_VALUE="$(openssl rand -base64 18 | tr -d '\n')"
  install -m 600 /dev/null .env
  {
    echo "ENVIRONMENT=production"
    echo "DATA_DIR=/data"
    echo "APP_SECRET=${APP_SECRET_VALUE}"
    echo "ADMIN_USERNAME=admin"
    echo "ADMIN_INITIAL_PASSWORD=${ADMIN_PASSWORD_VALUE}"
    echo "PUBLIC_BASE_URL=${PUBLIC_URL}"
    echo "COOKIE_SECURE=false"
    echo "SESSION_HOURS=12"
    echo "SEED_DEMO_STRUCTURE=true"
  } > .env
  install -m 600 /dev/null /root/teaching-choice-initial-password.txt
  printf '账号：admin\n初始密码：%s\n管理端：%s/admin\n' "${ADMIN_PASSWORD_VALUE}" "${PUBLIC_URL}" > /root/teaching-choice-initial-password.txt
fi

docker compose up -d --build

for attempt in $(seq 1 36); do
  if curl --fail --silent http://127.0.0.1/api/health >/dev/null; then
    break
  fi
  if [[ "${attempt}" -eq 36 ]]; then
    docker compose logs --tail=100 app
    echo "服务未能在预期时间内通过健康检查" >&2
    exit 1
  fi
  sleep 5
done

# 数据库已初始化后，从运行环境中移除初始密码；root 专用凭据文件保留供首次交接。
sed -i 's/^ADMIN_INITIAL_PASSWORD=.*/ADMIN_INITIAL_PASSWORD=/' .env
docker compose up -d

install -m 644 deploy/teaching-choice-backup.service /etc/systemd/system/teaching-choice-backup.service
install -m 644 deploy/teaching-choice-backup.timer /etc/systemd/system/teaching-choice-backup.timer
systemctl daemon-reload
systemctl enable --now teaching-choice-backup.timer

echo "部署完成：${PUBLIC_URL}"
echo "首次登录凭据保存在 /root/teaching-choice-initial-password.txt（权限 600）"

