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
- [x] PR #109 审查 P0 契约对齐（审计 / 刷新日志 / 插件 schema / Cron / activity / 分组文案）
- [x] PR #109 审查 P1：账号批量/导出、池批量+provider、设置多 Key/白名单/CF/部署、邮箱验证码与监听、审计增强

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
| 设置敏感字段 | 已支持 | 脱敏展示 + 仅在新值时提交 |
| 契约对齐修复（PR 审查 P0） | 已修 | 审计 `details/user_ip/trace_id`、刷新日志 `account_email/error_message`、插件 `config_schema.fields`、Cron `cron_expression`、概览 activity `timeline`、分组删除文案 |
| 账号导入 / 编辑 | 已补 | `/accounts` 支持 provider 导入（含 auto/custom）与编辑模态 |
| 账号批量 / 通知 / Token 刷新 / 导出 | 已补 | rowSelection 批量状态/删除/移组/通知；单行 Telegram 开关；导出二次验证 + `X-Export-Token` |
| 邮箱验证码提取 | 已补 | `/mailbox` 对接 `/api/emails/{email}/extract-verification` 一键复制 |
| 邮件 HTML 信任模式 / CID | 已补 | 基础消毒 + 可选信任模式 + `inline_resources` CID 重写（`utils/emailHtml.ts`） |
| 自动轮询引擎 | 最小可用 | `services/outlook/pollEngine.ts` + 邮箱页「开始/停止监听」；设置页 interval/count 持久化 |
| 外部 API 多 Key 表格 | 已补 | 设置页表格编辑 `external_api_keys`（name/api_key/allowed_emails/pool_access/enabled） |
| IP 白名单 / 危险端点开关 | 已补 | `external_api_ip_whitelist` + disable raw/wait/pool_* |
| CF 域名同步 / 部署信息 | 已补 | `POST /api/settings/cf-worker-sync-domains`；`deployment-info` + `trigger-update` |
| 池管理批量 / provider / claimed 裁剪 | 已补 | rowSelection 批量动作；provider 筛选；claimed 行仅 `force_release` |
| 审计增强 | 已补 | 时间本地化、details JSON 美化、动作色标、Trace 可复制 |
| 业务页 i18n | 部分 | `zh-CN`/`en-US` 已加 `outlook.*` 标题键；主页面 title 使用 formatMessage，表单文案仍有中文 default |
| 三栏 mailbox 工作台 / compact 视图 | 已补 | `/mailbox` 标准三栏（分组/账号/邮件+详情）+ 简洁列表；`ol_mailbox_view_mode` 持久化 |
| 布局拖拽 / compact poll 高级项 | 已补 | `ResizableWorkbench` 拖拽改宽/折叠/重置；`outlook_layout_state_*` 持久化；页顶 interval/maxCount 应用到 pollEngine |
| 旧 `templates/` + `static/js` | 保留 | 建议验收 SPA 后再移除默认入口 |
| 浏览器扩展 | 不变 | 继续走 `/api/external/*`，不依赖管理端 SPA |

建议下线顺序：

1. 验收 P0+P1：审计有数据、能加号/编辑/批量/导出、能复制验证码与监听、插件配置可读、Cron 可校验、设置多 Key/白名单/CF/部署可用、池批量与 claimed 裁剪正确
2. 网关默认切到 SPA `dist/`，旧前端保留路径或仅本机访问
3. 跑一轮真实账号冒烟（登录 → 概览活动 Tab → 账号导入/批量 → 邮件验证码/监听 → 池 → 设置敏感项/多 Key）
4. 三栏工作台 / compact / 布局拖拽已落地后，删除或归档 `templates/` 业务页与 `static/js/features/*`（保留扩展与健康检查）

## 开发代理

`config/proxy.ts` 将以下路径代理到 Flask（默认 `http://127.0.0.1:5000`）：

- `/api/`、`/login`、`/logout`、`/img/`
- `/token-tool/callback`（仅 OAuth 回调；SPA 页面 `/token-tool` 由 Umi 路由处理）
- `/healthz`

业务 Token 工具 API 走 `/api/token-tool/*`，不依赖页面路径代理。

## 邮箱池契约要点

- `GET /api/pool-admin/accounts` 响应：`{ items, total, page, page_size, total_pages }`
- 查询参数 `in_pool`：`true` | `false` | `all`（不要用 yes/no）；可选 `provider`
- 动作名：`move_into_pool` / `move_out_of_pool` / `restore_available` / `freeze` / `retire` / `force_release`
- **claimed 状态仅允许 `force_release`**（前端 `actionsForPoolRow` + 批量校验）

## 注意

- 不要手改 `src/services/ant-design-pro/`（openapi 生成目录）；业务 API 写在 `src/services/outlook/`
- Node >= 22
- `npm run simple` 不可逆，本项目不要执行
- 审查修复（P5 后）：pool-admin 契约对齐、token-tool 代理收敛、HTTP 错误体规范化
