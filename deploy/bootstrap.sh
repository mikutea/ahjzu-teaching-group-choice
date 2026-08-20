#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行此脚本" >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/ahjzu-teaching-group-choice}"
PUBLIC_URL="${PUBLIC_URL:-}"
ORIGIN_BIND_VALUE="${ORIGIN_BIND:-127.0.0.1}"
APP_CPU_LIMIT_VALUE="${APP_CPU_LIMIT:-1.5}"
APP_MEMORY_LIMIT_VALUE="${APP_MEMORY_LIMIT:-1g}"
APP_NOFILE_LIMIT_VALUE="${APP_NOFILE_LIMIT:-8192}"
ADMIN_PASSWORD_VALUE=""

if [[ ! -f "${APP_DIR}/docker-compose.yml" ]]; then
  echo "未找到 ${APP_DIR}/docker-compose.yml" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 curl openssl sqlite3
systemctl enable --now docker

cd "${APP_DIR}"
mkdir -p data
chown -R 10001:10001 data
chmod 750 data

CURRENT_SCHEMA_VERSION="$(awk '$1 == "SCHEMA_VERSION" && $2 == "=" && $3 ~ /^[0-9]+$/ { print $3; exit }' server/database.py)"
if [[ ! "${CURRENT_SCHEMA_VERSION}" =~ ^[0-9]+$ ]]; then
  echo "无法从 server/database.py 读取当前数据库结构版本" >&2
  exit 1
fi

BOOTSTRAP_PASSWORD_ACTIVE=false

scrub_initial_password() {
  if [[ -f .env ]]; then
    sed -i 's/^ADMIN_INITIAL_PASSWORD=.*/ADMIN_INITIAL_PASSWORD=/' .env || true
  fi
}

write_initial_password_without_argv() {
  local line=""
  local password_line_found=false
  local -a env_lines=()

  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == ADMIN_INITIAL_PASSWORD=* ]]; then
      env_lines+=("ADMIN_INITIAL_PASSWORD=${ADMIN_PASSWORD_VALUE}")
      password_line_found=true
    else
      env_lines+=("${line}")
    fi
  done < .env
  if [[ "${password_line_found}" != true ]]; then
    env_lines+=("ADMIN_INITIAL_PASSWORD=${ADMIN_PASSWORD_VALUE}")
  fi
  printf '%s\n' "${env_lines[@]}" > .env
}

database_bootstrap_state() {
  local database_path="data/teaching-choice.db"
  local schema_version=""
  local application_tables=""
  local admin_table=""
  local admin_rows=""

  if [[ ! -s "${database_path}" ]]; then
    printf 'empty\n'
    return
  fi
  schema_version="$(sqlite3 -readonly -batch -noheader "${database_path}" 'PRAGMA user_version;' 2>/dev/null)" || {
    printf 'invalid\n'
    return
  }
  application_tables="$(sqlite3 -readonly -batch -noheader "${database_path}" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%';" 2>/dev/null)" || {
    printf 'invalid\n'
    return
  }
  admin_table="$(sqlite3 -readonly -batch -noheader "${database_path}" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'admin_users';" 2>/dev/null)" || {
    printf 'invalid\n'
    return
  }

  # Opening SQLite and enabling WAL can leave a nonempty file before the
  # atomic schema transaction commits. That shell is safe to initialize again.
  if [[ "${schema_version}" == "0" && "${application_tables}" == "0" ]]; then
    printf 'empty\n'
    return
  fi
  if [[ "${schema_version}" == "${CURRENT_SCHEMA_VERSION}" && "${admin_table}" == "1" ]]; then
    admin_rows="$(sqlite3 -readonly -batch -noheader "${database_path}" \
      'SELECT COUNT(*) FROM admin_users;' 2>/dev/null)" || {
      printf 'invalid\n'
      return
    }
    if [[ "${admin_rows}" =~ ^[0-9]+$ && "${admin_rows}" -gt 0 ]]; then
      printf 'initialized\n'
      return
    fi
  fi
  printf 'invalid\n'
}

bootstrap_exit() {
  local status=$?
  trap - EXIT
  scrub_initial_password
  if [[ "${BOOTSTRAP_PASSWORD_ACTIVE}" == true ]]; then
    # A failed compose/health step may leave the bootstrap password in the
    # container configuration even after .env is scrubbed. Remove only that
    # failed app container; the next run recreates it from the clean env.
    docker compose rm -sf app >/dev/null 2>&1 || true
  fi
  ADMIN_PASSWORD_VALUE=""
  exit "${status}"
}

trap bootstrap_exit EXIT

if [[ -z "${PUBLIC_URL}" ]]; then
  PRIMARY_IP="$(hostname -I | awk '{print $1}')"
  PUBLIC_URL="http://${PRIMARY_IP}"
fi

COOKIE_SECURE_VALUE=false
if [[ "${PUBLIC_URL}" == https://* ]]; then
  COOKIE_SECURE_VALUE=true
fi

# Earlier releases persisted the bootstrap password for handoff.  Remove that
# exact legacy artifact and keep the new plaintext credential terminal-only.
rm -f -- /root/teaching-choice-initial-password.txt

DATABASE_BOOTSTRAP_STATE="$(database_bootstrap_state)"
if [[ "${DATABASE_BOOTSTRAP_STATE}" == "invalid" ]]; then
  echo "数据库不是可安全初始化的空壳，也不是含管理员账号的当前结构；请从受控备份恢复" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ "${DATABASE_BOOTSTRAP_STATE}" == "initialized" ]]; then
    echo "检测到现有数据库但缺少 .env，无法安全恢复应用密钥；请从受控备份恢复 .env" >&2
    exit 1
  fi
  APP_SECRET_VALUE="$(openssl rand -hex 32)"
  ADMIN_PASSWORD_VALUE="$(openssl rand -base64 18 | tr -d '\n')"
  BOOTSTRAP_PASSWORD_ACTIVE=true
  install -m 600 /dev/null .env
  {
    echo "ENVIRONMENT=production"
    echo "DATA_DIR=/data"
    echo "ORIGIN_BIND=${ORIGIN_BIND_VALUE}"
    echo "APP_CPU_LIMIT=${APP_CPU_LIMIT_VALUE}"
    echo "APP_MEMORY_LIMIT=${APP_MEMORY_LIMIT_VALUE}"
    echo "APP_NOFILE_LIMIT=${APP_NOFILE_LIMIT_VALUE}"
    echo "APP_SECRET=${APP_SECRET_VALUE}"
    echo "ADMIN_USERNAME=admin"
    echo "ADMIN_INITIAL_PASSWORD=${ADMIN_PASSWORD_VALUE}"
    echo "PUBLIC_BASE_URL=${PUBLIC_URL}"
    echo "COOKIE_SECURE=${COOKIE_SECURE_VALUE}"
    echo "TRUSTED_PROXY_IPS=${TRUSTED_PROXY_IPS:-}"
    echo "SESSION_HOURS=12"
    echo "SEED_DEMO_STRUCTURE=false"
    echo "APP_VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo local)"
  } > .env
elif [[ "${DATABASE_BOOTSTRAP_STATE}" == "empty" ]]; then
  # A previous first-run attempt may have failed before creating the database.
  # Its exit trap scrubbed .env, so generate and hand off a fresh credential.
  ADMIN_PASSWORD_VALUE="$(openssl rand -base64 18 | tr -d '\n')"
  BOOTSTRAP_PASSWORD_ACTIVE=true
  write_initial_password_without_argv
else
  # Existing databases authenticate against the stored password hash and never
  # need the bootstrap plaintext again.
  scrub_initial_password
fi
chmod 600 .env

if [[ -n "${ADMIN_PASSWORD_VALUE}" ]]; then
  printf '首次登录账号：admin\n首次登录密码：%s\n管理端：%s/admin\n' "${ADMIN_PASSWORD_VALUE}" "${PUBLIC_URL}"
  echo "请立即保存到受控密码管理器；服务器不会保留该明文密码。"
  echo "凭据已在首次构建前交接；若本次部署失败，请重新运行脚本并使用届时显示的新密码。"
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

# 数据库已初始化后，清除 .env 中的明文并强制重建 app 容器，确保
# docker inspect 也无法读取首次密码。任一步失败仍由 EXIT trap 清理。
scrub_initial_password
docker compose up -d --force-recreate --wait --wait-timeout 180 app
BOOTSTRAP_PASSWORD_ACTIVE=false
ADMIN_PASSWORD_VALUE=""

sed "s|@APP_DIR@|${APP_DIR}|g" deploy/teaching-choice-backup.service \
  > /etc/systemd/system/teaching-choice-backup.service
chmod 0644 /etc/systemd/system/teaching-choice-backup.service
install -m 644 deploy/teaching-choice-backup.timer /etc/systemd/system/teaching-choice-backup.timer
install -m 0700 deploy/update.sh /usr/local/sbin/teaching-choice-update
systemctl daemon-reload
systemctl enable --now teaching-choice-backup.timer

echo "部署完成：${PUBLIC_URL}"
echo "源站绑定：${ORIGIN_BIND_VALUE}:80；Cloudflare Tunnel 应指向 http://127.0.0.1:80"
echo "服务器不保存管理员明文密码。"
