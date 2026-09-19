#!/bin/bash
# =====================================================================
# weibo-readstack 一键部署脚本 —— 在 TrueNAS SCALE 的 Shell 里运行
# 用法: 把 weibo-readstack 目录放到 NAS (如 /mnt/tank/readstack), 然后
#       bash /mnt/tank/readstack/deploy.sh
# 特性: 可重复执行(幂等), 已有 .env 时不会覆盖
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

POOL="${POOL:-tank}"
APPS_DIR="/mnt/${POOL}/apps"

# ---- 前置检查 ----
command -v docker >/dev/null 2>&1 || { echo "[错误] 未找到 docker, 请确认是 TrueNAS SCALE 24.10+"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[错误] docker compose 不可用"; exit 1; }

# ---- 创建数据集与目录 (zfs 失败则退化为普通目录, 不影响运行) ----
zfs create -p "${POOL}/apps" 2>/dev/null || true
mkdir -p "${APPS_DIR}"/{karakeep/meili,trilium,weibo-sync}

# ---- 生成 .env (仅首次) ----
if [ ! -f .env ]; then
  NEXTAUTH_SECRET="$(openssl rand -base64 32 | tr -d '\n')"
  MEILI_KEY="$(openssl rand -hex 16)"
  NAS_IP="$(hostname -I | awk '{print $1}')"
  {
    echo "APPS_DIR=${APPS_DIR}"
    echo "NEXTAUTH_URL=http://${NAS_IP}:31000"
    echo "NEXTAUTH_SECRET=${NEXTAUTH_SECRET}"
    echo "MEILI_MASTER_KEY=${MEILI_KEY}"
    echo "KARAKEEP_API_KEY=CHANGE_ME"
    echo "TZ=Asia/Shanghai"
  } > .env
  echo "[信息] 已自动生成 .env (NAS地址: ${NAS_IP})"
fi

# ---- 启动整套服务 ----
echo "[信息] 开始构建并启动 4 个容器 (首次拉镜像约需几分钟)..."
docker compose up -d --build
sleep 5
docker compose ps

echo ""
echo "======================================================================"
echo " 部署完成! 接下来只剩 3 件手工事:"
echo "  1. 浏览器打开 http://$(hostname -I | awk '{print $1}'):31000 注册 Karakeep 管理员"
echo "     -> Settings -> API Keys 生成 key, 粘贴到本目录 .env 的 KARAKEEP_API_KEY"
echo "     -> 执行: docker compose up -d   (重载 key)"
echo "  2. 手机打开 http://$(hostname -I | awk '{print $1}'):31900 -> 扫码登录微博"
echo "  3. 回到 :31900 点一次[立即同步], 看到新增条数即全部打通"
echo "======================================================================"
