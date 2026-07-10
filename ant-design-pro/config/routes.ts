/**
 * @name umi 的路由配置
 * @description OutlookEmail 前端迁移路由骨架
 * @doc https://umijs.org/docs/guides/routes
 */
export default [
  {
    path: '/user',
    layout: false,
    routes: [
      {
        path: '/user/login',
        name: 'login',
        component: './user/login',
      },
      {
        path: '/user',
        redirect: '/user/login',
      },
      {
        name: '404',
        component: './exception/404',
        path: '/user/*',
      },
    ],
  },
  {
    path: '/overview',
    name: 'overview',
    icon: 'dashboard',
    component: './overview',
  },
  {
    path: '/mailbox',
    name: 'mailbox',
    icon: 'mail',
    component: './mailbox',
  },
  {
    path: '/accounts',
    name: 'accounts',
    icon: 'user',
    component: './accounts',
  },
  {
    path: '/groups',
    name: 'groups',
    icon: 'team',
    component: './groups',
  },
  {
    path: '/temp-emails',
    name: 'tempEmails',
    icon: 'clockCircle',
    component: './temp-emails',
  },
  {
    path: '/pool-admin',
    name: 'poolAdmin',
    icon: 'database',
    component: './pool-admin',
  },
  {
    path: '/plugins',
    name: 'plugins',
    icon: 'appstore',
    component: './plugins',
  },
  {
    path: '/refresh-log',
    name: 'refreshLog',
    icon: 'history',
    component: './refresh-log',
  },
  {
    path: '/settings',
    name: 'settings',
    icon: 'setting',
    component: './settings',
  },
  {
    path: '/audit',
    name: 'audit',
    icon: 'fileSearch',
    component: './audit',
  },
  {
    path: '/token-tool',
    name: 'tokenTool',
    icon: 'key',
    component: './token-tool',
  },
  {
    path: '/',
    redirect: '/overview',
  },
  {
    path: '*',
    layout: false,
    component: './exception/404',
  },
];
