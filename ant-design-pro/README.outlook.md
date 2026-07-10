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
- [ ] P3 邮件阅读
- [ ] P4 临时邮箱与插件
- [ ] P5 设置 / 审计 / 邮箱池 / Token 工具

## 注意

- 不要手改 `src/services/ant-design-pro/`（openapi 生成目录）；业务 API 写在 `src/services/outlook/`
- Node >= 22
- `npm run simple` 不可逆，本项目不要执行
