# weibo-readstack 部署包

离线稍后阅读 (Karakeep) + 笔记 (Trilium) + 微博收藏/点赞自动同步 (weibo-sync)，一个 compose 跑在 TrueNAS SCALE 上。

## 目录

```
docker-compose.yml     四合一部署栈
deploy.sh              一键部署脚本 (推荐, 自动生成密钥并启动)
.env.example           手动部署时的变量模板 (用 deploy.sh 则无需)
weibo-sync/            微博同步器源码 (扫码登录 + 轮询 + 推送)
weibo-readstack-plan/  细节方案文档 (浏览器打开其中的 .html)
```

## 快速开始

1. 整个文件夹拷到 NAS，例如 `/mnt/tank/readstack`，在 TrueNAS Web Shell 执行 `bash deploy.sh`，然后直接看第 4 步
   （或按下面手动流程）
2. `cp .env.example .env`，填 4 个值（NEXTAUTH_URL / NEXTAUTH_SECRET / MEILI_MASTER_KEY / KARAKEEP_API_KEY 可先留占位）
3. `docker compose up -d --build`
4. 打开 `http://NAS:31000` 注册 Karakeep 管理员 → Settings → API Keys 生成 key → 回填 `.env` 的 `KARAKEEP_API_KEY` → `docker compose up -d` 重载
5. 打开 `http://NAS:31900` → 扫码登录微博 → 立即同步一次

端口规划: Karakeep 31000 / Trilium 31080 / weibo-sync 31900（均为 5 位高位端口, 便于反代; 容器内部端口不变）
6. 之后在手机上刷微博，点收藏/点赞，10 分钟内自动进入 Karakeep，打标签“微博收藏 / 微博点赞”

## 注意

- 微博接口是非公开接口，`weibo-sync/weibo_api.py` 与 `weibo_qr.py` 顶部集中了全部端点常量，改版时只改常量。
- Cookie 约 1–3 个月过期一次，重新扫码即可，无需碰抓包工具。
- 细节与故障排查见包内 `方案文档.html`。
