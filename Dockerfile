# syntax=docker/dockerfile:1.6
#
# Toolbox 后端镜像（FastAPI + Typer + 转换引擎）
#
# 默认包含的引擎：MarkItDown、Docling、Pandoc、Vision-LLM
# 不包含：LibreOffice（镜像太大，按需在派生镜像里加：
#   RUN apt-get update && apt-get install -y --no-install-recommends libreoffice
# )
#
# 构建：
#   docker build -t toolbox-api .
#
# 运行：
#   docker run -p 8000:8000 \
#     -e TOOLBOX_ALLOWED_ORIGINS=https://tools.example.com \
#     -v $PWD/data:/data \
#     toolbox-api

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 系统依赖：
# - pandoc：Markdown ↔ DOCX / HTML / EPUB / RTF 引擎
# - libmagic1：MarkItDown 用 python-magic 嗅探格式
# - openjdk-17-jre-headless：opendataloader-pdf 引擎需要 JVM（benchmark
#   第一档 PDF→MD 准确率 0.907）
# - curl / ca-certificates：拉 uv 安装脚本与 Docling 模型
# - tini：稳健的 PID 1，转 SIGTERM 不留僵尸进程
RUN apt-get update && apt-get install -y --no-install-recommends \
        pandoc \
        libmagic1 \
        openjdk-17-jre-headless \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# 装 uv（Astral 官方一键脚本，固定到 /usr/local/bin）
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

WORKDIR /app

# 先复制依赖清单单独跑 uv sync，命中 Docker layer cache；
# 业务代码改动不会触发依赖重装
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project 2>/dev/null || uv sync --no-install-project

# 再拷源码并把项目装进 venv（含 pdf-pro extra → opendataloader-pdf）
COPY src ./src
COPY README.md ./
RUN uv sync --no-dev --extra pdf-pro

# 运行期：非 root 用户
RUN useradd --create-home --shell /bin/bash toolbox
USER toolbox

EXPOSE 8000

# 数据 / 模型缓存挂载点
ENV HF_HOME=/data/huggingface \
    DOCLING_CACHE=/data/docling \
    TOOLBOX_DATA_DIR=/data

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uv", "run", "toolbox", "serve", "--host", "0.0.0.0", "--port", "8000"]
