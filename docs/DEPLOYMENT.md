# 部署指南

Toolbox 支持两条等价的部署路径：

1. **自托管**：任何人 clone 后在自己机器 / 服务器一键起
2. **商用 SaaS**：作者把同一份代码部署到生产域名（例：`tools.example.com`）

两条路径**共用同一份代码**，区别只在环境变量与反向代理。

---

## 🏁 路径一：本地自托管（开发态）

适用于个人电脑或 LAN 内试用。

```bash
# 1. clone 全量（带 web 子模块）
git clone --recurse-submodules https://github.com/fmk618/ToolBox.git
cd ToolBox

# 2. 后端
uv sync
uv run toolbox serve            # → http://127.0.0.1:8000

# 3. 前端
cd web
npm install
npm run dev                     # → http://localhost:3000
```

无需任何额外配置，所有 19 个工具开箱即用。文件转换工具自动连本机后端。

---

## 🐳 路径二：自托管（生产态，Docker）

适用于单机服务器或私有云。

```bash
git clone --recurse-submodules https://github.com/fmk618/ToolBox.git
cd ToolBox
docker compose up -d --build
```

- `http://<server-ip>:3000` → Web 前端
- `http://<server-ip>:8000` → Backend API

Docker 镜像包含：

| 服务 | 镜像基础 | 大小（约） | 包含引擎                            |
| ---- | -------- | ---------- | ----------------------------------- |
| api  | `python:3.12-slim`  | ~600 MB    | MarkItDown · Docling · Pandoc · Vision-LLM |
| web  | `node:22-alpine`    | ~150 MB    | Next.js standalone                  |

**不包含**：LibreOffice（镜像会膨胀到 ~2 GB）。如需 Office→PDF，派生镜像：

```dockerfile
FROM toolbox-api:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice && rm -rf /var/lib/apt/lists/*
USER toolbox
```

---

## 🌐 路径三：商用 SaaS（域名 + HTTPS）

适用于把 Toolbox 部署到自己的域名提供服务。架构示意：

```
            ┌──────────────────────────────────────────────┐
            │              Caddy / Nginx                   │
            │   tools.example.com   api.tools.example.com  │
            └────────┬─────────────────────┬───────────────┘
                     │                     │
                ┌────▼──────┐         ┌────▼──────┐
                │   web     │         │   api     │
                │ :3000     │         │ :8000     │
                └───────────┘         └───────────┘
```

### 1. 准备域名与解析

- 主域 `tools.example.com` → 服务器公网 IP
- 子域 `api.tools.example.com` → 同一台或独立服务器

### 2. 调整 compose 环境变量

编辑 `docker-compose.yml`：

```yaml
services:
  api:
    environment:
      # 把允许的 Origin 改成你的前端域名，多个用逗号
      TOOLBOX_ALLOWED_ORIGINS: "https://tools.example.com"
    # 商用建议不暴露公网端口，靠反向代理转发
    expose:
      - "8000"
    # 删掉 ports 段

  web:
    build:
      args:
        # 注意：NEXT_PUBLIC_* 是构建期内联，必须在 build 时给对值
        NEXT_PUBLIC_API_BASE: "https://api.tools.example.com"
    expose:
      - "3000"
    # 删掉 ports 段
```

### 3. 反向代理

#### Caddy（推荐，自动 HTTPS）

`/etc/caddy/Caddyfile`：

```caddyfile
tools.example.com {
    encode zstd gzip
    reverse_proxy localhost:3000
}

api.tools.example.com {
    encode zstd gzip
    reverse_proxy localhost:8000

    # 文件上传体积上限（与 TOOLBOX_MAX_UPLOAD_MB 对齐）
    request_body {
        max_size 100MB
    }

    # Caddy 自带 rate limit 模块（需要 build 时 enable），或用本项目的
    # slowapi（已内置，TOOLBOX_RATE_LIMIT 控制）
}
```

Caddy 会自动从 Let's Encrypt 申请证书。

#### Nginx（含限流 + 上传上限 + 安全头模板）

完整模板见 [`scripts/nginx.toolbox.conf.example`](../scripts/nginx.toolbox.conf.example)：

```bash
sudo cp scripts/nginx.toolbox.conf.example /etc/nginx/conf.d/toolbox.conf
sudo certbot --nginx -d tools.example.com -d api.tools.example.com
sudo nginx -t && sudo systemctl reload nginx
```

模板包含：
- 每 IP 每分钟 10 次 `/tools/file-convert/convert` 上传限流（与后端 slowapi 双层保护）
- 每 IP 每分钟 120 次其他 API 调用限流
- `client_max_body_size 110m` 与 `TOOLBOX_MAX_UPLOAD_MB=100` 对齐
- `proxy_read_timeout 600s` 支持大 PDF 长跑
- `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` 安全头

### 4. 启动

```bash
docker compose up -d --build
sudo caddy reload --config /etc/caddy/Caddyfile
```

访问 `https://tools.example.com`。

---

## 🔐 环境变量参考

### 后端

| 变量                       | 默认                                         | 说明                                                       |
| -------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `TOOLBOX_ALLOWED_ORIGINS`  | `http://localhost:3000,http://127.0.0.1:3000` | CORS 白名单，逗号分隔。商用部署改成自家域名                  |
| `TOOLBOX_RATE_LIMIT`       | `20/minute`                                  | 文件转换接口每 IP 限流，slowapi 语法。空串关闭              |
| `TOOLBOX_MAX_UPLOAD_MB`    | `100`                                        | 上传体积上限（MB），超出直接 413                            |
| `HF_HOME`                  | `/data/huggingface`                          | Docling 用到的 HuggingFace 模型缓存目录                     |
| `DOCLING_CACHE`            | `/data/docling`                              | Docling 模型 / 中间产物缓存                                |
| `TOOLBOX_DATA_DIR`         | `/data`                                      | 数据根目录                                                  |

### 前端

| 变量                       | 默认                                | 说明                                                  |
| -------------------------- | ----------------------------------- | ----------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE`     | `http://127.0.0.1:8000`             | 后端 API 地址。**构建期注入**，运行时改要重新 build    |

---

## 🚀 路径四：前端走 Vercel + 后端自建（混合架构）

最适合作者「前端蹭 Vercel CDN，后端自己掌握」的商用场景。

### 前端（Vercel）

1. 在 Vercel 导入 [fmk618/ToolBox-web](https://github.com/fmk618/ToolBox-web)
2. 项目设置 → Environment Variables：
   ```
   NEXT_PUBLIC_API_BASE=https://api.tools.example.com
   ```
3. Deploy。Vercel 自动给一个 `*.vercel.app` 域名，可以再绑自家域名。

### 后端（自家服务器 + Docker）

只起 `api` 服务，省掉 `web`：

```bash
docker compose up -d --build api
```

记得 `TOOLBOX_ALLOWED_ORIGINS` 加上 Vercel 域名：

```yaml
environment:
  TOOLBOX_ALLOWED_ORIGINS: "https://tools.example.com,https://your-project.vercel.app"
```

---

## 📊 资源建议

| 用户规模               | CPU       | 内存    | 磁盘                              |
| ---------------------- | --------- | ------- | --------------------------------- |
| 个人 / 团队 (<100 DAU) | 1 vCPU    | 2 GB    | 10 GB（含 Docling 模型 ~3 GB）    |
| 小型 SaaS (<1k DAU)    | 2 vCPU    | 4 GB    | 20 GB                             |
| 中型 SaaS (>1k DAU)    | 4+ vCPU   | 8+ GB   | 单独存储卷给 `/data`              |

Vision-LLM 走云端 API，不消耗本地算力。文件转换是 CPU-bound，Docling 首次跑会冷启动 ~30s 加载 ML 模型。

---

## ✅ 健康检查

```bash
# API 是否就绪
curl https://api.tools.example.com/health
# → {"status":"ok"}

# 引擎是否齐全
curl https://api.tools.example.com/tools/file-convert/engines | jq

# 前端是否能拿到转换图
curl https://api.tools.example.com/tools/file-convert/routes | jq
```

---

## 🆘 常见问题

**Q：前端报 CORS 错误**

A：把 `TOOLBOX_ALLOWED_ORIGINS` 加上前端实际域名（含协议），重启 `api` 容器。

**Q：Docling 第一次转换很慢**

A：首跑下载 ML 模型（~3 GB），后续走缓存毫秒级。把 `/data` 挂成 named volume 让缓存持久化。

**Q：想要 opendataloader-pdf 顶级精度**

A：取消 `docker-compose.yml` 里 `opendataloader` service 的注释，并在前端「系统设置」配置 hybrid backend URL。后端 `core/engines_graph.py` 里的引擎优先级会自动选用它。

**Q：要不要装 LibreOffice？**

A：仅当你需要 Office (docx/pptx/xlsx) → PDF。装了镜像膨胀到 ~2 GB，不要装在小机型上。
