# GitHub Actions + Cloudflare Pages + 腾讯云部署教程

本文是 FMKTools 当前项目最适合的生产部署方案：前端由 Cloudflare Pages 托管，后端和 FFmpeg 运行在腾讯云服务器，GitHub Actions 负责测试、构建后端镜像和自动更新服务器。

## 一、先确定最终架构

```text
用户浏览器
    │
    ├── https://app.example.com
    │       └── Cloudflare Pages（Next.js 静态导出）
    │
    └── https://api.example.com
            └── Cloudflare Tunnel
                    └── 腾讯云 127.0.0.1:8000
                            └── Docker Compose：FastAPI + FFmpeg

GitHub push
    ├── ToolBox-web push → Cloudflare Pages 自动构建前端
    └── ToolBox beta push → GitHub Actions
            ├── uv run pytest
            ├── 构建 toolbox-api Docker 镜像
            ├── 推送 ghcr.io/fmk618/toolbox-api
            └── Tailscale SSH → docker compose pull/up -d
```

### 为什么不选截图中的 Jenkins

Jenkins 不是本项目当前最合适的选择。项目代码已经在 GitHub，前端又是 Cloudflare Pages，GitHub Actions 可以直接使用 GitHub 权限、缓存和审计能力，不需要额外维护 Jenkins 主机、插件、升级和凭据。

只有在将来同时管理很多项目、需要复杂审批或已有稳定 Jenkins 团队时，才值得引入 Jenkins。Registry、Nexus、Gitea、GitLab 和 OneDev 是仓库或制品基础设施，不是本项目所需的最短自动部署链路。

## 二、部署前准备

需要准备：

- 一个 GitHub `fmk618/ToolBox` 根仓库。
- 一个 GitHub `fmk618/ToolBox-web` 前端子模块仓库。
- 一个腾讯云 Linux 服务器，建议至少 2 vCPU、4 GB 内存和 40 GB 可用磁盘。
- 一个由 Cloudflare 托管 DNS 的域名。
- 一个 Cloudflare Pages 项目。
- 一个 Cloudflare Tunnel。
- 一个 Tailscale 网络（推荐用于 GitHub Actions 连接服务器）。

媒体解析会消耗 CPU、临时磁盘和公网带宽。不要用 1 GB 内存的小型服务器直接承载 Docling、FFmpeg 和 yt-dlp 的生产任务。

## 三、配置 Cloudflare Pages 前端

前端是独立 Git 仓库，不要在 Cloudflare Pages 中选择根仓库的 `web` 子目录。按以下步骤操作：

1. 登录 Cloudflare Dashboard，打开 **Workers & Pages → Create application → Pages → Connect to Git**。
2. 选择 `fmk618/ToolBox-web`。
3. 生产分支选择前端仓库实际发布分支（通常是 `main`）。
4. 构建设置填写：

   ```text
   Framework preset: None（或 Next.js，若当前账户界面提供该选项）
   Build command: TAURI=1 npm run build
   Build output directory: out
   Root directory: /
   Node.js version: 22
   ```

   `TAURI=1` 会让本项目的 `next.config.ts` 使用 `output: "export"`，生成可以放到 Pages 的静态 `out` 目录。不要把默认的 standalone `.next` 目录当作 Pages 输出目录。

5. 在 Pages 的 **Settings → Environment variables → Production** 增加：

   ```text
   NEXT_PUBLIC_API_BASE=https://api.example.com
   NEXT_PUBLIC_SHARE_BASE_URL=https://app.example.com/
   ```

   这两个值会在构建期写入浏览器 JavaScript。它们不是密码，不能把 API key、SSH key 或 GHCR token 放进任何 `NEXT_PUBLIC_*` 变量。

6. 先执行一次部署，确认 `https://<project>.pages.dev` 可以打开首页。
7. 在 Pages 中绑定自己的前端域名，例如 `app.example.com`。绑定完成后，生产 API 的 CORS 白名单必须使用最终的 HTTPS 域名，而不是只使用 `pages.dev` 地址。

### 前端代码如何触发部署

修改前端时，在 `ToolBox-web` 仓库提交并推送：

```bash
cd web
# 修改前端代码
npm run lint
npm run build
# 在 ToolBox-web 仓库中提交并推送到发布分支
```

Cloudflare Pages 会自动构建。根仓库只保存前端子模块指针；如果根仓库需要同步到最新前端提交，需要在根仓库执行：

```bash
git -C web pull origin main
git add web
git commit -m "chore(web): 更新前端子模块"
git push
```

## 四、准备腾讯云服务器

以下命令在腾讯云服务器执行。把 `/opt/toolbox` 作为固定部署目录，因为仓库中的 GitHub Actions 工作流会使用它。

### 1. 安装 Docker

使用腾讯云镜像或 Docker 官方安装方式安装 Docker Engine 和 Compose v2，并确认：

```bash
docker --version
docker compose version
```

不要开放 Docker TCP API，不要把 `/var/run/docker.sock` 映射到公网服务。

### 2. 创建非 root 部署账号

```bash
sudo adduser --disabled-password --gecos "" toolbox-deploy
sudo usermod -aG docker toolbox-deploy
sudo install -d -o toolbox-deploy -g toolbox-deploy -m 750 /opt/toolbox
```

`docker` 用户组在 Linux 上具有接近 root 的能力，因此这个账号仍然只用于部署，不用于登录日常操作；同时应关闭 root SSH 登录和密码登录。更高安全要求可以改用 rootless Docker。

### 3. 首次放置 Compose 文件

```bash
sudo -u toolbox-deploy git clone --depth 1 https://github.com/fmk618/ToolBox.git /opt/toolbox
sudo -u toolbox-deploy cp /opt/toolbox/.env.product /opt/toolbox/.env
sudo -u toolbox-deploy vi /opt/toolbox/.env
```

服务器只需要 `docker-compose.api.yml` 和 `.env`，不需要运行前端容器。`.env` 至少设置：

```dotenv
TOOLBOX_API_IMAGE=ghcr.io/fmk618/toolbox-api:latest
TOOLBOX_ALLOWED_ORIGINS=https://app.example.com
TOOLBOX_RATE_LIMIT=20/minute
TOOLBOX_MEDIA_MAX_PENDING=4
TOOLBOX_MEDIA_JOB_TTL=1800
TOOLBOX_MEDIA_MAX_INPUT_MB=200
TOOLBOX_MEDIA_MAX_DOWNLOAD_MB=500
TOOLBOX_MEDIA_MAX_DURATION_SECONDS=7200
```

`.env` 含有部署配置，不能提交到 GitHub。若同时有生产和预发布环境，应为每个环境使用不同的 API 镜像和 CORS 域名。

### 4. 配置 GHCR 只读凭据

服务器需要从 GitHub Container Registry 拉取私有镜像：

1. 在 GitHub 创建只拥有 `read:packages` 的凭据；不要使用 Actions 的写入 token 保存到服务器。
2. 以部署账号登录 GHCR：

   ```bash
   sudo -iu toolbox-deploy
   printf '%s' '只读_GHCR_TOKEN' | docker login ghcr.io -u 'GitHub用户名' --password-stdin
   exit
   ```

3. 确认凭据归部署账号所有，并限制权限：

   ```bash
   sudo chmod 600 /home/toolbox-deploy/.docker/config.json
   ```

如果镜像是公开的，可以不配置这一步，但生产环境仍建议控制镜像可见性。

## 五、用 Cloudflare Tunnel 暴露 API

API Compose 文件只绑定 `127.0.0.1:8000`，所以腾讯云安全组不需要开放 8000。Tunnel 由服务器主动向 Cloudflare 建立出站连接，浏览器再通过 `api.example.com` 访问。

### 1. 安装并创建 Tunnel

在腾讯云服务器安装 `cloudflared`，然后执行登录和创建命令：

```bash
cloudflared tunnel login
cloudflared tunnel create toolbox-api
cloudflared tunnel route dns toolbox-api api.example.com
```

记录命令返回的 Tunnel UUID。为 Tunnel 创建配置文件，例如 `/etc/cloudflared/config.yml`：

```yaml
tunnel: YOUR_TUNNEL_UUID
credentials-file: /etc/cloudflared/YOUR_TUNNEL_UUID.json

ingress:
  - hostname: api.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

把 Tunnel 凭据复制到配置中指定的位置，并限制文件权限：

```bash
sudo chmod 600 /etc/cloudflared/YOUR_TUNNEL_UUID.json
sudo cloudflared tunnel ingress validate
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

### 2. 启动 API 并检查 Tunnel

先手工启动一次：

```bash
cd /opt/toolbox
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml up -d api
curl http://127.0.0.1:8000/health
curl https://api.example.com/health
```

两个请求都应返回：

```json
{"status":"ok"}
```

Cloudflare Tunnel 连接正常后，腾讯云安全组只保留 SSH（最好通过 Tailscale），不开放 8000、3000、5432 或 Docker API。若使用 Cloudflare Tunnel，服务器可以不拥有任何 API 公网入站端口。

## 六、配置 Tailscale SSH

GitHub 托管 Runner 的公网 IP 会变化，不适合把某一个 GitHub IP 永久写进腾讯云安全组。推荐让 Workflow 临时加入 Tailscale，再通过 Tailscale 地址 SSH 到服务器。

### 1. 服务器加入 Tailscale

在服务器安装 Tailscale，并将服务器放入专用 tag，例如 `tag:deploy`。启用 Tailscale SSH 后，只允许 CI tag 访问服务器的 22 端口。

Tailscale ACL 的关键规则示意如下，实际配置按你的 tailnet 管理员和 tag owner 规则调整：

```json
{
  "tagOwners": {
    "tag:deploy": ["autogroup:admin"],
    "tag:github-actions": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["tag:github-actions"],
      "dst": ["tag:deploy:22"]
    }
  ]
}
```

### 2. 创建 SSH 密钥和 known hosts

为 GitHub Actions 创建专用密钥对，不要复用个人密钥：

```bash
ssh-keygen -t ed25519 -f toolbox-actions -C toolbox-actions
```

把 `toolbox-actions.pub` 追加到服务器部署账号的 `authorized_keys`，并把私钥作为 GitHub Actions secret 保存。首次连接时核对服务器指纹，然后把固定的 known-hosts 内容作为另一个 secret 保存：

```bash
ssh-keyscan -H YOUR_TAILSCALE_SERVER_NAME
```

不要在 Workflow 中无条件执行 `ssh-keyscan` 并立即信任结果，那会失去主机密钥校验的意义。

## 七、配置 GitHub Actions Secrets

打开根仓库 **Settings → Secrets and variables → Actions**，增加以下 secrets：

| Secret | 内容 |
| --- | --- |
| `DEPLOY_HOST` | 腾讯服务器的 Tailscale IP 或 MagicDNS 名称 |
| `DEPLOY_PORT` | 通常为 `22` |
| `DEPLOY_USER` | `toolbox-deploy` |
| `DEPLOY_SSH_KEY` | 专用 SSH 私钥全文 |
| `DEPLOY_KNOWN_HOSTS` | 已核对的服务器 known_hosts 行 |
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth client ID |
| `TS_OAUTH_SECRET` | Tailscale OAuth secret |

Tailscale OAuth client 只能创建 CI 所需的 tag，不能授予整个 tailnet 的管理权限。`DEPLOY_SSH_KEY`、`TS_OAUTH_SECRET` 和 GHCR token 都只能出现在 Secrets 中，不能写入 `.env`、日志或代码。

如果暂时不能使用 Tailscale，可以省略两个 `TS_*` secret，让 Workflow 连接公网 SSH；这时必须在腾讯云安全组和 `sshd_config` 中关闭密码登录、禁止 root 登录、仅允许密钥登录，并用额外的防火墙策略保护 SSH。公网 SSH 是退而求其次的方案。

## 八、首次运行自动部署

仓库中的 `.github/workflows/deploy-api.yml` 已包含完整链路：

1. 在 `beta` 分支推送后触发，或从 Actions 页面手动触发。
2. 使用锁定的 `uv.lock` 执行后端测试。
3. 使用根目录 `Dockerfile` 构建 API 镜像；镜像内包含 FFmpeg/FFprobe。
4. 将 `latest` 和 commit SHA 两个 tag 推送到 GHCR。
5. 通过 Tailscale（如果配置）和 SSH 连接 `/opt/toolbox`。
6. 执行：

   ```bash
   docker compose -f docker-compose.api.yml pull api
   docker compose -f docker-compose.api.yml up -d --remove-orphans api
   ```

第一次可以在 GitHub Actions 页面点击 **Run workflow**。成功后检查：

```bash
curl https://api.example.com/health
curl -i -X OPTIONS https://api.example.com/tools/video-extract/metadata \
  -H 'Origin: https://app.example.com' \
  -H 'Access-Control-Request-Method: POST'
```

第二个请求应包含允许的 CORS 响应头。然后从 `https://app.example.com` 打开视频解析、音频转换和视频编辑工具进行实际测试。

## 九、日常更新流程

### 后端更新

```bash
# 在本地根仓库
 git checkout beta
 # 修改 src/、Dockerfile 或后端依赖
 uv run pytest -q
 git add src pyproject.toml uv.lock Dockerfile docker-compose.api.yml
 git commit -m "feat(media): 更新媒体处理能力"
 git push origin beta
```

推送后不需要登录服务器手工构建。Actions 通过后，服务器会自动拉取新镜像并重启 API 容器。

### 前端更新

在 `ToolBox-web` 仓库提交并推送到 Pages 生产分支。Cloudflare Pages 会单独构建和发布，后端不会因为纯前端改动重启。

### 只修改服务器配置

修改 `/opt/toolbox/.env` 后执行：

```bash
cd /opt/toolbox
docker compose -f docker-compose.api.yml up -d api
```

修改 CORS、媒体限制或 API 地址后必须重启容器。修改 Cloudflare Tunnel 配置后执行：

```bash
sudo cloudflared tunnel ingress validate
sudo systemctl restart cloudflared
```

## 十、回滚方式

Workflow 同时发布 commit SHA tag。出现故障时，在 GHCR 找到上一个成功的 SHA，并在服务器 `.env` 中将镜像固定到该 tag：

```dotenv
TOOLBOX_API_IMAGE=ghcr.io/fmk618/toolbox-api:PREVIOUS_COMMIT_SHA
```

然后执行：

```bash
cd /opt/toolbox
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml pull api
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml up -d api
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml ps api
```

确认修复后再把 `.env` 改回 `latest`。更严格的生产环境可以使用镜像 digest 固定版本，而不是使用可变的 `latest`。

## 十一、安全与资源检查清单

部署完成后逐项确认：

- [ ] API 只通过 `https://api.example.com` 访问，浏览器和文档中不出现腾讯云裸 IP。
- [ ] 腾讯云安全组没有开放 8000、3000 或 Docker API。
- [ ] Cloudflare Tunnel 只转发到 `127.0.0.1:8000`。
- [ ] `TOOLBOX_ALLOWED_ORIGINS` 只包含真实前端 HTTPS 域名，不使用 `*`。
- [ ] SSH 禁止 root 和密码登录，部署账号不是 root。
- [ ] GitHub Actions 使用专用 SSH key、Tailscale OAuth 凭据和 GHCR 权限。
- [ ] GHCR 拉取凭据只有 `read:packages`，没有写入权限。
- [ ] `.env`、`.env.*` 中的密钥没有提交到 Git。
- [ ] API 任务有并发、大小、时长、超时和临时磁盘限制。
- [ ] 视频 URL 由后端校验，不能访问 localhost、私网地址或云元数据地址。
- [ ] Cloudflare 上传限制不超过当前套餐；大文件后续使用腾讯云 COS 临时签名直传。
- [ ] 服务器 `/data` 有足够磁盘，并设置监控和清理策略。

## 十二、常见问题

### Pages 构建成功但页面刷新 404

确认构建命令是 `TAURI=1 npm run build`，输出目录是 `out`，而不是 `.next`。本项目的工具路由会在构建期由 manifest 生成静态参数。

### 页面打开但请求 API 失败

依次检查：

1. Pages 的 `NEXT_PUBLIC_API_BASE` 是否为 `https://api.example.com`。
2. `curl https://api.example.com/health` 是否成功。
3. API `.env` 的 `TOOLBOX_ALLOWED_ORIGINS` 是否包含当前前端域名。
4. 浏览器开发者工具中的请求是否仍指向旧的 localhost 地址。
5. 修改环境变量后是否重新触发了 Pages 构建。

### Actions 能推送镜像但无法 SSH

检查 Tailscale OAuth tag、ACL、`DEPLOY_HOST` 是否为 Tailscale 地址、专用私钥是否匹配，以及 `DEPLOY_KNOWN_HOSTS` 是否为同一台服务器的指纹。不要为了绕过问题而关闭 `StrictHostKeyChecking`。

### 容器更新后视频任务失败

查看日志：

```bash
cd /opt/toolbox
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml logs --tail=200 api
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml exec api ffmpeg -version
sudo -iu toolbox-deploy docker compose -f docker-compose.api.yml exec api ffprobe -version
```

确认 `/data` 可写、磁盘足够，并检查媒体输入是否超过 `.env` 中的大小和时长限制。

### 为什么不把大文件直接经过 Pages

Cloudflare、浏览器、反向代理和 API 都可能有请求体大小与超时限制。当前 MVP 适合小于配置上限的文件；用户量或文件体积增长后，应让浏览器使用腾讯 COS 的短期签名直接上传，再让 API 任务处理对象存储中的文件。
