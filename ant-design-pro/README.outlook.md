# OutlookEmail 前端（Ant Design Pro）

本目录是从 [ant-design-pro](https://github.com/ant-design/ant-design-pro) 迁入的前端模板库，用于逐步替换仓库根目录 `templates/` + `static/js` 旧前端。

## 技术栈

- React 19 + Umi Max 4 + Ant Design 6 + ProComponents
- 开发代理到 Flask（默认 `http://127.0.0.1:5000`）
- 鉴权：Flask session cookie + CSRF（`X-CSRFToken`）

## 本地开发

```bash
# 终端 1：后端
python start.py
# 或
python web_outlook_app.py

# 终端 2：前端
cd ant-design-pro
npm install
npm start
```

浏览器打开 `http://localhost:8000`。

环境变量（可选）：

- `FLASK_PROXY_TARGET`：覆盖默认后端代理地址

## 路由与旧前端映射

| 新路由 | 旧 data-page / 入口 |
|---|---|
| `/overview` | dashboard |
| `/mailbox` | mailbox |
| `/accounts` | 账号相关（mailbox 侧栏） |
| `/groups` | 分组相关 |
| `/temp-emails` | temp-emails |
| `/pool-admin` | pool-admin |
| `/plugins` | 插件管理 |
| `/refresh-log` | refresh-log |
| `/settings` | settings |
| `/audit` | audit |
| `/token-tool` | /token-tool |
| `/user/login` | /login |

## 鉴权适配 API（后端）

- `POST /login` `{ password }`
- `GET /api/auth/current-user`
- `POST /api/auth/logout`
- `GET /api/csrf-token`

## 迁移进度

- [x] P0 基础设施（proxy / CSRF / login / 路由骨架）
- [x] P1 概览 Dashboard（`/overview` → `/api/overview/*`）
- [x] P2 账号与分组（`/accounts` `/groups`）
- [x] P3 邮件阅读（`/mailbox` → `/api/emails/*` `/api/email/*`）
- [x] P4 临时邮箱与插件（`/temp-emails` `/plugins`）
- [x] P5 设置 / 审计 / 邮箱池 / Token 工具 / 刷新日志
- [x] 审查修复：pool-admin 契约、token-tool 代理、HTTP 错误体、设置敏感字段

## 生产构建与联调

```bash
cd ant-design-pro
npm install
npm run build          # 产出 dist/
npm run preview        # 本地预览 dist，默认 :8000
```

联调方式（二选一）：

1. **开发双进程**（推荐迁移期）：Flask `:5000` + `npm start` `:8000`，依赖 `config/proxy.ts`
2. **静态资源挂载**：将 `dist/` 交给 Nginx/Caddy，`/api` `/login` `/logout` `/img` `/healthz` 反代到 Flask；SPA fallback 到 `index.html`

注意：

- 生产环境 **Umi proxy 不生效**，必须在网关层做同源反代，否则 cookie/CSRF 跨域会失败
- Flask 仍可独立服务旧 `templates/` 前端；新旧前端可并行，直到 SPA 验收完成
- 契约回归：`python -m unittest tests.test_auth_spa_adapters tests.test_overview_api_contract tests.test_accounts_groups_api_contract tests.test_emails_api_contract tests.test_temp_emails_plugins_api_contract tests.test_p5_api_contract -v`

## 残余差距 / 下线旧前端策略

| 项 | 状态 | 说明 |
|---|---|---|
| 业务主页面 SPA | 已迁移 | overview / mailbox / accounts / groups / temp-emails / pool-admin / plugins / settings / audit / token-tool / refresh-log |
| 设置敏感字段 | 已支持 | 脱敏展示 + 仅在新值时提交；多 Key 编辑器仍可后续增强 |
| 外部 API 多 Key 表格 | 未迁移 | 旧页有完整 multi-key 编辑；SPA 目前只支持单 Key 更新 |
| 布局拖拽 / compact poll 高级项 | 未迁移 | 旧 `layout-manager` 能力非 MVP |
| 旧 `templates/` + `static/js` | 保留 | 建议验收 SPA 后再移除默认入口 |
| 浏览器扩展 | 不变 | 继续走 `/api/external/*`，不依赖管理端 SPA |

建议下线顺序：

1. 网关默认切到 SPA `dist/`，旧前端保留路径或仅本机访问
2. 跑一轮真实账号冒烟（登录 → 概览 → 账号 → 邮件 → 池 → 设置敏感项）
3. 删除/归档 `templates/` 业务页与 `static/js/features/*`（保留扩展与健康检查）

## 开发代理

`config/proxy.ts` 将以下路径代理到 Flask（默认 `http://127.0.0.1:5000`）：

- `/api/`、`/login`、`/logout`、`/img/`
- `/token-tool/callback`（仅 OAuth 回调；SPA 页面 `/token-tool` 由 Umi 路由处理）
- `/healthz`

业务 Token 工具 API 走 `/api/token-tool/*`，不依赖页面路径代理。

## 邮箱池契约要点

- `GET /api/pool-admin/accounts` 响应：`{ items, total, page, page_size, total_pages }`
- 查询参数 `in_pool`：`true` | `false` | `all`（不要用 yes/no）
- 动作名：`move_into_pool` / `move_out_of_pool` / `restore_available` / `freeze` / `retire` / `force_release`

## 注意

- 不要手改 `src/services/ant-design-pro/`（openapi 生成目录）；业务 API 写在 `src/services/outlook/`
- Node >= 22
- `npm run simple` 不可逆，本项目不要执行
- 审查修复（P5 后）：pool-admin 契约对齐、token-tool 代理收敛、HTTP 错误体规范化
