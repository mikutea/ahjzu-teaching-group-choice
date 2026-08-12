# 独立虚拟机部署

## 建议规格

- Ubuntu Server 24.04 LTS；
- 2 vCPU、2 GiB 内存、16 GiB 系统盘；
- 一张接入校园网的 VirtIO 网卡；
- 独立 VM，不与 VM 103 共用应用进程或数据库；
- 校内 HTTP 80 作为源站入口，公网访问通过 Cloudflare Tunnel 提供 HTTPS。

## 部署步骤

```bash
git clone https://github.com/mikutea/ahjzu-teaching-group-choice.git /opt/ahjzu-teaching-group-choice
cd /opt/ahjzu-teaching-group-choice
chmod +x deploy/bootstrap.sh
sudo APP_DIR=/opt/ahjzu-teaching-group-choice ./deploy/bootstrap.sh
```

脚本会安装 Docker、生成独立应用密钥和随机初始管理员密码、构建容器、执行健康检查并启用每日 SQLite 在线备份。首次凭据仅保存在 VM 的 `/root/teaching-choice-initial-password.txt`，权限为 `600`。

## 更新

旧版本首次升级到带更新器的版本时，先从已审核并完整指定的提交安装脚本；不要先启动
新容器或迁移数据库：

```bash
commit="完整的 40 位 Git 提交号"
sudo git -c safe.directory=/opt/ahjzu-teaching-group-choice \
  -C /opt/ahjzu-teaching-group-choice fetch origin
sudo git -c safe.directory=/opt/ahjzu-teaching-group-choice \
  -C /opt/ahjzu-teaching-group-choice show \
  "${commit}:deploy/update.sh" | sudo install -m 0700 /dev/stdin \
  /usr/local/sbin/teaching-choice-update
sudo UPDATE_TARGET="${commit}" /usr/local/sbin/teaching-choice-update
```

后续升级只需：

```bash
sudo /usr/local/sbin/teaching-choice-update
```

更新脚本以 root 单入口运行，并使用文件锁拒绝并发升级。它会先创建在线备份和旧镜像
回滚标签，再在隔离的备份副本上执行真实数据库迁移与业务数据摘要对比。只有预演通过
才进入维护窗：关闭 Tunnel、迁移正式库、等待新容器健康并完成本机检查，最后恢复
Tunnel 并验收公网健康地址。维护窗内失败会在公网恢复前还原旧数据库和旧镜像。

每次发布的提交、镜像 ID、升级前数据库及校验值记录在
`/var/backups/teaching-choice/releases/`。该目录仍位于同一 VM，只用于版本回滚；
正式使用前还应把备份加密同步到异机或异盘，并定期做隔离恢复演练。

## Cloudflare Tunnel

生产域名为 `https://choice.example.com`，使用独立的远程管理 Tunnel
`ahjzu-teaching-choice`，源站规则指向 VM 本机 `http://localhost:80`。

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
数据库升级前必须先生成在线备份，数据库迁移失败时镜像与数据库必须成对恢复。
名额权威账本不依赖 Redis，原因和并发验收标准
见 [architecture.md](architecture.md)。

为避免 Tunnel 后的所有学生共用同一个登录限流键，应把 Cloudflare 请求进入
应用容器时的 Docker 网关地址写入 `.env` 的 `TRUSTED_PROXY_IPS`。系统只会在
直连来源匹配该白名单时读取 Cloudflare 的 `CF-Connecting-IP`，其他来源不能
通过伪造请求头绕过限流。例如当前 VM 的配置为：

```dotenv
PUBLIC_BASE_URL=https://choice.example.com
COOKIE_SECURE=true
TRUSTED_PROXY_IPS=172.18.0.1
```

## 备份与恢复边界

- 每日备份保存在 `data/backups/`，默认保留 30 份；
- 每份备份完成后自动运行 SQLite 完整性检查；
- 恢复前必须关闭容器，并先复制当前数据库与 `-wal`、`-shm` 文件到独立安全位置；
- 不提供“一键覆盖”恢复脚本，避免误操作生产数据。
