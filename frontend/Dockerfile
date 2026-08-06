# ============================================================
# 阶段一：构建（pnpm 官方镜像 + node）
# ============================================================
FROM node:22-alpine AS builder

WORKDIR /app

# 先装依赖（利用层缓存）
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

# 构建静态文件
COPY . .
RUN pnpm build

# ============================================================
# 阶段二：Nginx 托管
# ============================================================
FROM nginx:alpine

# 把构建产物放进 Nginx 的静态目录
COPY --from=builder /app/dist /usr/share/nginx/html

# 覆盖 Nginx 默认配置（含 /api 反向代理）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80