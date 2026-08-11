# 独立虚拟机部署

## 建议规格

- Ubuntu Server 24.04 LTS；
- 2 vCPU、2 GiB 内存、16 GiB 系统盘；
- 一张接入校园网的 VirtIO 网卡；
- 独立 VM，不与 VM 103 共用应用进程或数据库；
- 默认只开放校内 HTTP 80，跨网访问前配置域名、HTTPS 和访问控制。

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

## 备份与恢复边界

- 每日备份保存在 `data/backups/`，默认保留 30 份；
- 每份备份完成后自动运行 SQLite 完整性检查；
- 恢复前必须关闭容器，并先复制当前数据库与 `-wal`、`-shm` 文件到独立安全位置；
- 不提供“一键覆盖”恢复脚本，避免误操作生产数据。

