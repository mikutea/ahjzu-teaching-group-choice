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

```bash
cd /opt/ahjzu-teaching-group-choice
git pull --ff-only
sudo docker compose up -d --build
sudo docker compose exec -T app python -m server.maintenance check
```

## Cloudflare Tunnel

生产域名为 `https://class.miyuo.net`，使用独立的远程管理 Tunnel
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

## 备份与恢复边界

- 每日备份保存在 `data/backups/`，默认保留 30 份；
- 每份备份完成后自动运行 SQLite 完整性检查；
- 恢复前必须关闭容器，并先复制当前数据库与 `-wal`、`-shm` 文件到独立安全位置；
- 不提供“一键覆盖”恢复脚本，避免误操作生产数据。
