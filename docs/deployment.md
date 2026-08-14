# 独立虚拟机部署

## 建议规格

- Ubuntu Server 24.04 LTS；
- 2 vCPU、2 GiB 内存、16 GiB 系统盘；
- 一张接入校园网的 VirtIO 网卡；
- 独立 VM，不与 VM 103 共用应用进程或数据库；
- 宿主机回环地址的 HTTP 80 作为源站入口，公网访问通过 Cloudflare Tunnel 提供 HTTPS。

## 部署步骤

```bash
git clone https://github.com/mikutea/ahjzu-teaching-group-choice.git /opt/ahjzu-teaching-group-choice
cd /opt/ahjzu-teaching-group-choice
chmod +x deploy/bootstrap.sh
sudo APP_DIR=/opt/ahjzu-teaching-group-choice \
  PUBLIC_URL=https://class.miyuo.net \
  ORIGIN_BIND=127.0.0.1 \
  ./deploy/bootstrap.sh
```

脚本会安装 Docker、生成独立应用密钥和随机初始管理员密码、构建容器、执行健康检查并启用每日 SQLite 在线备份。首次凭据仅保存在 VM 的 `/root/teaching-choice-initial-password.txt`，权限为 `600`。
`ORIGIN_BIND=127.0.0.1` 会让宿主机 80 端口只在回环地址监听，供同机
`cloudflared` 访问，不向校园网或公网直接暴露。只有明确需要受控的局域网直连、并已经
配置主机防火墙时，才可显式改为 `0.0.0.0`。

在建议的 2 vCPU、2 GiB 虚拟机上，应用容器默认限制为 1.5 CPU 和 1 GiB 内存，给
Docker、SQLite 页缓存、`cloudflared` 与系统服务保留余量。可通过 `.env` 中的
`APP_CPU_LIMIT`、`APP_MEMORY_LIMIT` 调整，但正式环境不应取消资源上限。应用保持单个
Uvicorn worker：名额写入由 SQLite 单写事务串行化，多 worker 不会提高原子抢位吞吐，
反而会扩大写锁竞争。

## 更新

首次安装更新器，或需要从已审核提交刷新更新器时，先从完整指定的提交提取并校验脚本；
不要先启动新容器或改动当前数据库：

```bash
set -euo pipefail
commit="完整的 40 位 Git 提交号"
repo="/opt/ahjzu-teaching-group-choice"
temporary="$(mktemp)"
trap 'rm -f "${temporary}"' EXIT
sudo git -c safe.directory=/opt/ahjzu-teaching-group-choice \
  -C "${repo}" fetch origin
sudo git -c safe.directory=/opt/ahjzu-teaching-group-choice \
  -C "${repo}" show "${commit}:deploy/update.sh" > "${temporary}"
expected_blob="$(sudo git -c safe.directory=/opt/ahjzu-teaching-group-choice \
  -C "${repo}" rev-parse "${commit}:deploy/update.sh")"
test "$(git hash-object "${temporary}")" = "${expected_blob}"
bash -n "${temporary}"
sudo install -m 0700 "${temporary}" /usr/local/sbin/teaching-choice-update
sudo UPDATE_TARGET="${commit}" /usr/local/sbin/teaching-choice-update
```

后续升级只需：

```bash
commit="经审核的完整 40 位 Git 提交号"
sudo UPDATE_TARGET="${commit}" /usr/local/sbin/teaching-choice-update
```

更新器拒绝分支名、标签名和缩写提交号，避免审核后远端引用移动导致部署内容变化。

更新脚本以 root 单入口运行，并使用文件锁拒绝并发更新。它会先创建在线备份和旧镜像
回滚标签，再在隔离的备份副本上校验当前 schema 版本、数据库完整性与业务数据摘要。
系统不提供跨 schema 的旧库自动迁移；版本不等于当前 schema v3 时会在维护窗前拒绝发布。
只有预检通过才进入维护窗：关闭 Tunnel、再次校验静止的正式库、等待新容器健康并完成
本机检查，最后恢复 Tunnel 并验收公网健康地址。维护窗内失败会在公网恢复前还原旧数据库
和旧镜像。

每次发布的提交、镜像 ID、升级前数据库及校验值记录在
`/var/backups/teaching-choice/releases/`。该目录仍位于同一 VM，只用于版本回滚；
正式使用前必须另建加密的异机备份，并定期做隔离恢复演练。

## Cloudflare Tunnel

生产域名为 `https://class.miyuo.net`，使用独立的远程管理 Tunnel
`ahjzu-teaching-choice`，源站规则指向 VM 本机 `http://127.0.0.1:80`。
Compose 默认把宿主机 80 端口绑定到 `127.0.0.1`；Tunnel 由
`cloudflared` 主动建立出站连接，因此不需要开放源站入站端口。

从 Cloudflare 控制台取得该 Tunnel 的连接 token 后，只把 token 写入服务器：

```bash
sudo install -d -m 0755 /etc/cloudflared
sudo install -m 0600 /dev/stdin /etc/cloudflared/teaching-choice.token
sudo APP_DIR=/opt/ahjzu-teaching-group-choice \
  TOKEN_FILE=/etc/cloudflared/teaching-choice.token \
  /opt/ahjzu-teaching-group-choice/deploy/install-cloudflared.sh
```

安装脚本使用 Cloudflare 官方 Ubuntu 24.04 软件源，并以无登录权限的
`cloudflared` 系统用户运行。Token 文件最终权限为 `root:cloudflared 0640`，
不会写入 Git、环境变量或进程参数。公网验收通过后，仍应保留
`/api/health`、学生页、管理端登录页和二维码域名一致性检查。

应用整体由 Docker Compose 管理，SQLite 数据只写入宿主机 `data/` 持久目录；
镜像以 Git 提交号作为版本标签，升级脚本同时记录实际 image ID 并保留旧镜像回滚标签。
应用更新前必须先生成在线备份；当前数据库校验或新容器验收失败时，镜像与数据库必须
成对恢复。旧 schema 数据库不会被就地转换，应先按当前名单格式重新建立新库。
名额权威账本不依赖 Redis，原因和并发验收标准
见 [architecture.md](architecture.md)。

为避免 Tunnel 后的所有学生共用同一个登录限流键，应把 Cloudflare 请求进入
应用容器时的 Docker 网关地址写入 `.env` 的 `TRUSTED_PROXY_IPS`。系统只会在
直连来源匹配该白名单时读取 Cloudflare 的 `CF-Connecting-IP`，其他来源不能
通过伪造请求头绕过限流。例如当前 VM 的配置为：

```dotenv
ORIGIN_BIND=127.0.0.1
APP_CPU_LIMIT=1.5
APP_MEMORY_LIMIT=1g
PUBLIC_BASE_URL=https://class.miyuo.net
COOKIE_SECURE=true
TRUSTED_PROXY_IPS=172.18.0.1
```

## HTTPS 与 HSTS

先在 Cloudflare 验证 `class.miyuo.net` 始终可用 HTTPS，并启用该主机名的 HTTP 到
HTTPS 跳转。Cloudflare 的 `Always Use HTTPS` 会影响同一区域中的全部主机名；只有
`miyuo.net` 的所有站点都支持 HTTPS 时才能在区域级启用，否则应使用仅匹配
`class.miyuo.net` 的 Redirect Rule。

为避免影响同一区域的其他子域，优先建立只匹配
`(http.host eq "class.miyuo.net")` 的 Response Header Transform Rule，以 `Set static`
设置 `Strict-Transport-Security`。确认 Tunnel、边缘证书和恢复流程稳定后再分阶段调整：

1. 先使用 `max-age=2592000`（30 天），不附加 `includeSubDomains` 或 `preload`；
2. 观察一个完整发布与恢复周期，确认所有访问路径持续支持 HTTPS；
3. 再逐步延长 `max-age`。只有所有子域都已审核并永久支持 HTTPS 时，才考虑
   `includeSubDomains`；满足长期运维承诺前不要启用 `preload`。

HSTS 生效后，在 `max-age` 到期前移除 HTTPS、暂停 Cloudflare 或改为 DNS only 会使
浏览器无法访问站点。上线验收应确认 `Strict-Transport-Security` 的 `max-age` 为预期的
非零值，并保留回退计划。

操作前复核 Cloudflare 官方的
[Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/)、
[HSTS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/http-strict-transport-security/)
与 [Response Header Transform Rules](https://developers.cloudflare.com/rules/transform/response-header-modification/)
说明。

## 备份与恢复边界

真实名单工作文件（包括 `.xls`、`.xlsx`、`.csv`）只允许放在部署负责人明确控制的非仓库目录。项目根目录、
Docker 构建上下文和父级 `data/` 工作目录均设置了防提交规则；不得使用强制添加绕过。导入后的完整证件号不会写入
SQLite 或备份，备份仍应按包含学生姓名、学号和选择结果的敏感数据进行加密与访问控制。

- 每日备份保存在 `data/backups/`，默认保留 30 份；
- 每份备份完成后自动运行 SQLite 完整性检查；
- 恢复前必须关闭容器，并先复制当前数据库与 `-wal`、`-shm` 文件到独立安全位置；
- 不提供“一键覆盖”恢复脚本，避免误操作生产数据。

本机 `data/backups/` 与 `/var/backups/teaching-choice/releases/` 只能用于快速回滚，
不构成灾难恢复备份。生产负责人还必须建立以下独立流程：

- 在离开 VM 前完成客户端加密，把密文复制到不同主机且最好不同存储故障域；
- 加密密钥与备份副本分开保管，远端写入凭据采用最小权限并放在 root 专用凭据文件或
  已选定平台的密钥管理服务中，不写入仓库或项目 `.env`；
- 远端副本设置保留期和防误删策略，并监控最近成功时间、大小与校验值；
- 定期在隔离目录解密恢复，运行 SQLite 深度检查并记录恢复耗时，验证 RPO/RTO。

仓库不预置任何远程备份地址、账号或密钥；应在选定且验证过备份平台后单独配置。

## 依赖与基础镜像门禁

CI 固定使用 `pip-audit==2.10.1`，分别审计生产与开发 requirements；发现已知漏洞或
依赖解析失败都会阻断合并。GitHub Actions 均固定到完整提交 SHA。`Dockerfile` 使用
Docker Hub 官方 API 于 2026-08-13 返回的 `python:3.12-slim` 多架构清单 digest；后续
升级 Python 基础镜像时，必须重新核验官方摘要、构建并跑完整回归，不得只改回浮动标签。
