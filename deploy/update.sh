#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR="/opt/ahjzu-teaching-group-choice"
DATA_DIR="${APP_DIR}/data"
ENV_FILE="${APP_DIR}/.env"
UPDATE_TARGET="${UPDATE_TARGET:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行更新脚本" >&2
  exit 1
fi

if [[ ! "${UPDATE_TARGET}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "必须通过 UPDATE_TARGET 指定经审核的完整 40 位 Git 提交号" >&2
  exit 1
fi
UPDATE_TARGET="${UPDATE_TARGET,,}"

if [[ "${TEACHING_CHOICE_UPDATE_REEXEC:-0}" != "1" ]]; then
  runtime_copy="/run/teaching-choice-update.$$.sh"
  install -m 0700 "$0" "${runtime_copy}"
  exec env TEACHING_CHOICE_UPDATE_REEXEC=1 \
    TEACHING_CHOICE_UPDATE_COPY="${runtime_copy}" \
    UPDATE_TARGET="${UPDATE_TARGET}" bash "${runtime_copy}"
fi

if [[ "$(readlink -f "${APP_DIR}")" != "${APP_DIR}" ]]; then
  echo "应用目录不符合预期：${APP_DIR}" >&2
  exit 1
fi
if [[ ! -f "${APP_DIR}/docker-compose.yml" || ! -f "${ENV_FILE}" ]]; then
  echo "应用目录缺少 docker-compose.yml 或 .env" >&2
  exit 1
fi

exec 9>/run/lock/teaching-choice-update.lock
if ! flock -n 9; then
  echo "另一个教学组抢选更新正在运行" >&2
  exit 1
fi

GIT=(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}")
COMPOSE=(docker compose --project-directory "${APP_DIR}" -f "${APP_DIR}/docker-compose.yml")
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_DIR="/var/backups/teaching-choice/releases/${STAMP}"
PHASE="PRECHECK"
TIMER_WAS_ACTIVE=0
PREFLIGHT_DIR=""
OLD_COMMIT=""
OLD_FULL_COMMIT=""
ROLLBACK_TAG=""
FINAL_BACKUP_READY=0

log() {
  printf '[teaching-choice-update] %s\n' "$*"
}

set_env() {
  local key="$1" value="$2" temporary
  temporary="$(mktemp "${APP_DIR}/.env.tmp.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    index($0, key "=") == 1 {
      if (!written) print key "=" value
      written = 1
      next
    }
    { print }
    END { if (!written) print key "=" value }
  ' "${ENV_FILE}" > "${temporary}"
  chown --reference="${ENV_FILE}" "${temporary}"
  chmod --reference="${ENV_FILE}" "${temporary}"
  mv -f -- "${temporary}" "${ENV_FILE}"
  [[ "$(grep -c "^${key}=" "${ENV_FILE}")" -eq 1 ]]
}

cleanup_preflight() {
  if [[ -n "${PREFLIGHT_DIR:-}" ]]; then
    local resolved
    resolved="$(readlink -f "${PREFLIGHT_DIR}" 2>/dev/null || true)"
    case "${resolved}" in
      "${DATA_DIR}"/.release-preflight-*) rm -rf -- "${resolved}" ;;
      "") ;;
      *) log "拒绝清理非预期发布预检临时目录：${resolved}" ;;
    esac
  fi
}

restore_source_checkout() {
  if [[ -z "${OLD_FULL_COMMIT:-}" ]]; then
    return 0
  fi
  local current
  current="$("${GIT[@]}" rev-parse HEAD 2>/dev/null || true)"
  if [[ "${current}" == "${OLD_FULL_COMMIT}" ]]; then
    return 0
  fi
  if [[ -n "$("${GIT[@]}" status --porcelain)" ]]; then
    log "源码目录在更新过程中出现额外改动，拒绝自动覆盖"
    return 1
  fi
  "${GIT[@]}" reset --hard "${OLD_FULL_COMMIT}"
}

restore_old_release() {
  log "新版本未通过本机验收，正在恢复升级前数据库和镜像"
  local failed_dir file
  if (( FINAL_BACKUP_READY != 1 )) \
    || [[ ! -s "${RELEASE_DIR}/pre-upgrade.db" ]] \
    || [[ ! -s "${RELEASE_DIR}/pre-upgrade.db.sha256" ]] \
    || ! sha256sum -c "${RELEASE_DIR}/pre-upgrade.db.sha256"; then
    log "最终回滚备份尚未就绪，拒绝移动当前数据库"
    return 1
  fi
  if ! "${COMPOSE[@]}" stop -t 10 app; then
    log "无法停止失败的新容器"
    return 1
  fi
  failed_dir="${RELEASE_DIR}/failed-live-db"
  if ! install -d -m 0700 "${failed_dir}"; then
    return 1
  fi
  for file in \
    "${DATA_DIR}/teaching-choice.db" \
    "${DATA_DIR}/teaching-choice.db-wal" \
    "${DATA_DIR}/teaching-choice.db-shm"; do
    if [[ -e "${file}" ]]; then
      if ! mv -- "${file}" "${failed_dir}/$(basename "${file}")"; then
        return 1
      fi
    fi
  done
  for file in \
    "${DATA_DIR}/teaching-choice.db" \
    "${DATA_DIR}/teaching-choice.db-wal" \
    "${DATA_DIR}/teaching-choice.db-shm"; do
    if [[ -e "${file}" ]]; then
      return 1
    fi
  done
  if ! install -o 10001 -g 10001 -m 0640 \
    "${RELEASE_DIR}/pre-upgrade.db" "${DATA_DIR}/teaching-choice.db"; then
    return 1
  fi
  if ! install -o root -g root -m 0600 "${RELEASE_DIR}/env.before" "${ENV_FILE}"; then
    return 1
  fi
  if ! restore_source_checkout; then
    return 1
  fi
  if ! set_env SEED_DEMO_STRUCTURE false || ! set_env APP_VERSION "rollback-${OLD_COMMIT}"; then
    return 1
  fi
  if "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 180 app \
    && curl -fsS --max-time 5 http://127.0.0.1/api/health >/dev/null; then
    if ! systemctl start cloudflared.service \
      || ! systemctl is-active --quiet cloudflared.service; then
      systemctl stop cloudflared.service || true
      return 1
    fi
    log "已恢复旧镜像 ${ROLLBACK_TAG} 与升级前数据库"
    return 0
  fi
  log "自动恢复失败；Tunnel 保持关闭。恢复文件位于 ${RELEASE_DIR}"
  return 1
}

on_exit() {
  local result="$?"
  trap - EXIT
  cleanup_preflight
  if (( result != 0 )); then
    case "${PHASE:-PRECHECK}" in
      PRECHECK|PREFLIGHT_OK)
        restore_source_checkout || true
        ;;
      ENV_MUTATING|ENV_READY)
        if [[ -f "${RELEASE_DIR}/env.before" ]]; then
          install -o root -g root -m 0600 "${RELEASE_DIR}/env.before" "${ENV_FILE}"
        fi
        restore_source_checkout || true
        ;;
      QUIESCING)
        if [[ -f "${RELEASE_DIR}/env.before" ]]; then
          install -o root -g root -m 0600 "${RELEASE_DIR}/env.before" "${ENV_FILE}" || true
          set_env SEED_DEMO_STRUCTURE false || true
          set_env APP_VERSION "rollback-${OLD_COMMIT}" || true
        fi
        restore_source_checkout || true
        if ! "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 180 app \
          || ! curl -fsS --max-time 5 http://127.0.0.1/api/health >/dev/null; then
          log "旧应用未能恢复，Tunnel 保持关闭，请人工处理"
        else
          systemctl start cloudflared.service || true
        fi
        ;;
      ROLLBACK_READY|VALIDATING|DB_VALIDATED)
        restore_old_release || true
        ;;
      LOCAL_HEALTHY)
        systemctl start cloudflared.service || true
        ;;
    esac
  fi
  if (( TIMER_WAS_ACTIVE )); then
    systemctl start teaching-choice-backup.timer || true
  fi
  case "${TEACHING_CHOICE_UPDATE_COPY:-}" in
    /run/teaching-choice-update.*.sh) rm -f -- "${TEACHING_CHOICE_UPDATE_COPY}" ;;
  esac
  exit "${result}"
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap on_exit EXIT

install -d -m 0700 "${RELEASE_DIR}"
if [[ -n "$("${GIT[@]}" status --porcelain)" ]]; then
  echo "仓库存在未提交改动，拒绝更新" >&2
  exit 1
fi
systemctl is-active --quiet cloudflared.service
compose_up_help="$(docker compose up --help)"
if ! grep -q -- '--wait' <<< "${compose_up_help}"; then
  echo "Docker Compose 版本不支持 --wait，拒绝无健康门禁更新" >&2
  exit 1
fi

OLD_CONTAINER_ID="$("${COMPOSE[@]}" ps -q app)"
if [[ -z "${OLD_CONTAINER_ID}" || "$(docker inspect -f '{{.State.Running}}' "${OLD_CONTAINER_ID}")" != "true" ]]; then
  echo "旧应用容器未运行" >&2
  exit 1
fi
CURRENT_STATUS="$("${COMPOSE[@]}" exec -T app python -c \
  'from server.config import Config; from server.database import connect; c=connect(Config.from_env().database_path); print(c.execute("SELECT status FROM settings WHERE id=1").fetchone()[0]); c.close()')"
if [[ "${CURRENT_STATUS}" != "closed" ]]; then
  echo "当前抢选仍开放，请先在管理端关闭活动" >&2
  exit 1
fi

if systemctl is-active --quiet teaching-choice-backup.timer; then
  TIMER_WAS_ACTIVE=1
fi
systemctl stop teaching-choice-backup.timer
for _ in $(seq 1 30); do
  if ! systemctl is-active --quiet teaching-choice-backup.service; then
    break
  fi
  sleep 1
done
if systemctl is-active --quiet teaching-choice-backup.service; then
  echo "备份服务仍在运行，拒绝并发更新" >&2
  exit 1
fi

OLD_FULL_COMMIT="$("${GIT[@]}" rev-parse HEAD)"
OLD_COMMIT="${OLD_FULL_COMMIT:0:12}"
OLD_IMAGE_ID="$(docker inspect -f '{{.Image}}' "${OLD_CONTAINER_ID}")"
ROLLBACK_TAG="teaching-group-choice:rollback-${OLD_COMMIT}"
docker image tag "${OLD_IMAGE_ID}" "${ROLLBACK_TAG}"
install -m 0600 "${ENV_FILE}" "${RELEASE_DIR}/env.before"

log "创建发布预检源备份"
BACKUP_CONTAINER="$("${COMPOSE[@]}" exec -T app \
  python -m server.maintenance backup --retain 30 | tail -n 1)"
if [[ ! "${BACKUP_CONTAINER}" =~ ^/data/backups/teaching-choice-[0-9]{8}T[0-9]{6}([0-9]{6})?Z\.db$ ]]; then
  echo "备份路径格式异常：${BACKUP_CONTAINER}" >&2
  exit 1
fi
BACKUP_HOST="${DATA_DIR}/backups/$(basename "${BACKUP_CONTAINER}")"
if [[ ! -f "${BACKUP_HOST}" || ! -s "${BACKUP_HOST}" ]]; then
  echo "升级前备份不存在或为空" >&2
  exit 1
fi
install -m 0600 "${BACKUP_HOST}" "${RELEASE_DIR}/preflight-source.db"
sha256sum "${RELEASE_DIR}/preflight-source.db" > "${RELEASE_DIR}/preflight-source.db.sha256"

log "获取并构建 ${UPDATE_TARGET}"
"${GIT[@]}" fetch --prune origin
TARGET_COMMIT="$("${GIT[@]}" rev-parse --verify "${UPDATE_TARGET}^{commit}")"
if [[ "${TARGET_COMMIT}" != "${UPDATE_TARGET}" ]]; then
  echo "UPDATE_TARGET 未解析为指定的提交对象" >&2
  exit 1
fi
"${GIT[@]}" merge --ff-only "${TARGET_COMMIT}"
NEW_COMMIT="$("${GIT[@]}" rev-parse --short=12 HEAD)"
NEW_IMAGE="teaching-group-choice:${NEW_COMMIT}"
docker build --build-arg "APP_VERSION=${NEW_COMMIT}" --tag "${NEW_IMAGE}" "${APP_DIR}"
NEW_IMAGE_ID="$(docker image inspect -f '{{.Id}}' "${NEW_IMAGE}")"
IMAGE_VERSION="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "${NEW_IMAGE}")"
if [[ "${IMAGE_VERSION}" != "${NEW_COMMIT}" ]]; then
  echo "镜像版本标签与提交号不一致" >&2
  exit 1
fi

printf 'old_commit=%s\nold_image=%s\nnew_commit=%s\nnew_image=%s\nbackup=%s\n' \
  "${OLD_COMMIT}" "${OLD_IMAGE_ID}" "${NEW_COMMIT}" "${NEW_IMAGE_ID}" \
  "${RELEASE_DIR}/pre-upgrade.db" > "${RELEASE_DIR}/manifest"

PREFLIGHT_DIR="$(mktemp -d "${DATA_DIR}/.release-preflight-${STAMP}.XXXXXX")"
chown 10001:10001 "${PREFLIGHT_DIR}"
chmod 0700 "${PREFLIGHT_DIR}"
install -o 10001 -g 10001 -m 0640 \
  "${RELEASE_DIR}/preflight-source.db" "${PREFLIGHT_DIR}/teaching-choice.db"
log "在隔离备份副本上校验当前数据库版本与业务数据"
docker run --rm --env-file "${ENV_FILE}" \
  -e DATA_DIR=/work \
  -e DATABASE_PATH=/work/teaching-choice.db \
  -e SEED_DEMO_STRUCTURE=false \
  -e ADMIN_INITIAL_PASSWORD= \
  --mount "type=bind,src=${PREFLIGHT_DIR},dst=/work" \
  "${NEW_IMAGE}" python -m server.maintenance release-check \
  | tee "${RELEASE_DIR}/preflight.log"
PHASE="PREFLIGHT_OK"

PHASE="ENV_MUTATING"
set_env SEED_DEMO_STRUCTURE false
set_env APP_VERSION "${NEW_COMMIT}"
PHASE="ENV_READY"

PHASE="QUIESCING"
log "进入维护窗并校验正式数据库"
systemctl stop cloudflared.service
"${COMPOSE[@]}" stop -t 30 app
FINAL_STATUS="$(docker run --rm --env-file "${ENV_FILE}" \
  -e DATA_DIR=/work -e DATABASE_PATH=/work/teaching-choice.db \
  --mount "type=bind,src=${DATA_DIR},dst=/work" "${ROLLBACK_TAG}" python -c \
  'from server.config import Config; from server.database import connect; c=connect(Config.from_env().database_path); print(c.execute("SELECT status FROM settings WHERE id=1").fetchone()[0]); c.close()')"
if [[ "${FINAL_STATUS}" != "closed" ]]; then
  echo "维护窗开始前活动状态已经变化，拒绝发布" >&2
  exit 1
fi
log "从静止数据库生成最终回滚备份"
docker run --rm --env-file "${ENV_FILE}" \
  -e DATA_DIR=/work -e DATABASE_PATH=/work/teaching-choice.db \
  --mount "type=bind,src=${DATA_DIR},dst=/work" \
  "${ROLLBACK_TAG}" python -m server.maintenance backup --retain 30 >/dev/null
FINAL_BACKUP="$(find "${DATA_DIR}/backups" -maxdepth 1 -type f \
  -name 'teaching-choice-*.db' -printf '%T@|%p\n' | sort -nr | head -n 1 | cut -d'|' -f2-)"
if [[ -z "${FINAL_BACKUP}" || ! -s "${FINAL_BACKUP}" ]]; then
  echo "无法定位维护窗最终回滚备份" >&2
  exit 1
fi
install -m 0600 "${FINAL_BACKUP}" "${RELEASE_DIR}/pre-upgrade.db"
sha256sum "${RELEASE_DIR}/pre-upgrade.db" > "${RELEASE_DIR}/pre-upgrade.db.sha256"
sha256sum -c "${RELEASE_DIR}/pre-upgrade.db.sha256"
FINAL_BACKUP_READY=1
PHASE="ROLLBACK_READY"
PHASE="VALIDATING"
docker run --rm --env-file "${ENV_FILE}" \
  -e DATA_DIR=/work \
  -e DATABASE_PATH=/work/teaching-choice.db \
  -e SEED_DEMO_STRUCTURE=false \
  -e ADMIN_INITIAL_PASSWORD= \
  --mount "type=bind,src=${DATA_DIR},dst=/work" \
  "${NEW_IMAGE}" python -m server.maintenance release-check \
  | tee "${RELEASE_DIR}/production-release-check.log"
PHASE="DB_VALIDATED"

"${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 180 app
RUNNING_CONTAINER_ID="$("${COMPOSE[@]}" ps -q app)"
RUNNING_IMAGE_ID="$(docker inspect -f '{{.Image}}' "${RUNNING_CONTAINER_ID}")"
if [[ "${RUNNING_IMAGE_ID}" != "${NEW_IMAGE_ID}" ]]; then
  echo "实际运行镜像与发布预检镜像不一致" >&2
  exit 1
fi
"${COMPOSE[@]}" exec -T app python -m server.maintenance check
curl -fsS --max-time 5 http://127.0.0.1/api/health >/dev/null
curl -fsS --max-time 5 http://127.0.0.1/api/public/info >/dev/null
curl -fsS --max-time 5 http://127.0.0.1/admin >/dev/null
PHASE="LOCAL_HEALTHY"

systemctl start cloudflared.service
systemctl is-active --quiet cloudflared.service
for _ in $(seq 1 12); do
  if curl -fsS --max-time 10 https://choice.example.com/api/health >/dev/null; then
    break
  fi
  sleep 5
done
curl -fsS --max-time 10 https://choice.example.com/api/health >/dev/null
unit_copy="$(mktemp /run/teaching-choice-backup.service.XXXXXX)"
sed "s|@APP_DIR@|${APP_DIR}|g" "${APP_DIR}/deploy/teaching-choice-backup.service" \
  > "${unit_copy}"
install -m 0644 "${unit_copy}" /etc/systemd/system/teaching-choice-backup.service
rm -f -- "${unit_copy}"
install -m 0644 "${APP_DIR}/deploy/teaching-choice-backup.timer" \
  /etc/systemd/system/teaching-choice-backup.timer
systemctl daemon-reload
install -m 0700 "${APP_DIR}/deploy/update.sh" /usr/local/sbin/teaching-choice-update
PHASE="COMPLETE"
log "更新完成：${NEW_COMMIT}，发布记录：${RELEASE_DIR}"
