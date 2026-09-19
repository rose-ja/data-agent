# DataAgent 前端

电商问数智能体的聊天式前端：React 19 + Vite 6 + TypeScript + Tailwind CSS。

## 功能

- 聊天式问数交互，内置示例问题
- 手动解析 `POST /api/query` 的 SSE 流式响应（UTF-8 分块解码）
- StepRail 展示各阶段实时进度（关键词抽取 / 三路召回 / SQL 生成 / 执行）
- ResultTable 渲染查询结果表格，支持停止生成

## 本地开发

```bash
pnpm install
pnpm dev        # http://localhost:5173，/api 默认代理到 http://127.0.0.1:8000
```

后端地址可通过 `VITE_DEV_PROXY_TARGET` 环境变量覆盖；生产构建产物由 Nginx 托管并对 `/api/` 反向代理（SSE 已关闭缓冲）。
