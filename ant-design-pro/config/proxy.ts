/**
 * @name 代理的配置
 * @see 在生产环境 代理是无法生效的，所以这里没有生产环境的配置
 * -------------------------------
 * The agent cannot take effect in the production environment
 * so there is no configuration of the production environment
 * For details, please see
 * https://pro.ant.design/docs/deploy
 *
 * @doc https://umijs.org/docs/guides/proxy
 *
 * 本仓库前端迁移：开发时把 /api、/login、/logout、/img 代理到 Flask 后端。
 * 默认后端地址见仓库根目录 .env.example 中 PORT=5000。
 * 可通过环境变量 FLASK_PROXY_TARGET 覆盖。
 */
const FLASK_TARGET = process.env.FLASK_PROXY_TARGET || 'http://127.0.0.1:5000';

const flaskProxy = {
  '/api/': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
  '/login': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
  '/logout': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
  '/img/': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
  // 仅代理 OAuth 回调；SPA 页面 /token-tool 由 Umi 自己处理
  // 业务 API 已由 /api/ 覆盖（含 /api/token-tool/*）
  '/token-tool/callback': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
  '/healthz': {
    target: FLASK_TARGET,
    changeOrigin: true,
  },
};

export default {
  dev: flaskProxy,
  /**
   * @name 详细的代理配置
   * @doc https://github.com/chimurai/http-proxy-middleware
   */
  test: {
    '/api/': {
      target: 'https://pro-api.ant-design-demo.workers.dev',
      changeOrigin: true,
    },
  },
  pre: {
    '/api/': {
      target: 'your pre url',
      changeOrigin: true,
    },
  },
};
