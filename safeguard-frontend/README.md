# SafeGuard-AI 用户前端

安卫智脑（SafeGuard-AI）用户前端 — Vue 3 pnpm monorepo。

## 快速开始

```bash
pnpm install            # 安装所有依赖
pnpm dev:admin          # 启动管理后台 (localhost:5173)
pnpm dev:pwa            # 启动巡检 PWA (localhost:5174)
```

## 项目结构

- `packages/shared/` — 共享代码（API 客户端、类型、组件、Composables、Stores、工具函数）
- `packages/admin-web/` — EHS 管理后台（桌面端 · Element Plus · ECharts）
- `packages/inspector-pwa/` — 巡检 PWA（移动端 · Vant UI · 离线队列 · Service Worker）

## 技术栈

Vue 3 · TypeScript · Vite · Element Plus · Vant UI · ECharts · Pinia · PWA · Turborepo

## 后端依赖

需要 SafeGuard-AI FastAPI 后端运行在 `localhost:8000`。
Vite dev server 自动代理 `/api` 请求到后端。

新增后端端点需求见 `docs/superpowers/specs/2026-06-15-safeguard-ai-frontend-design.md` §9。

## 命令

| 命令 | 说明 |
|------|------|
| `pnpm dev:admin` | 启动管理后台开发服务器 |
| `pnpm dev:pwa` | 启动巡检 PWA 开发服务器 |
| `pnpm build` | 构建全部包 |
| `pnpm test` | 运行全部测试 |
| `pnpm lint` | 运行 ESLint 检查 |
| `pnpm typecheck` | 运行 TypeScript 类型检查 |
