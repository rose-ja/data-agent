# ============================================================
# 阶段一：依赖构建（用 uv 官方镜像，装好全部依赖）
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

# 先只复制依赖清单，再安装——利用 Docker 层缓存
# 只要 pyproject.toml / uv.lock 没变，这层缓存就不会失效，重建秒级完成
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ============================================================
# 阶段二：运行镜像（只带运行时必要的东西，体积更小）
# ============================================================
FROM python:3.14-slim

WORKDIR /app

# 从构建阶段把虚拟环境整体拷过来（含全部依赖）
COPY --from=builder /app/.venv .venv

# 复制项目代码
COPY . .

# 让容器里的 python 命令直接使用虚拟环境
ENV PATH="/app/.venv/bin:$PATH"

# 暴露后端端口（仅供文档说明，真正映射在 compose 里做）
EXPOSE 8000

# 生产启动：uvicorn 直接跑 ASGI 应用，不带 --reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]