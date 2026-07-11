/**
 * @name umi 的路由配置
 * @description OutlookEmail 前端迁移路由（账号 / 邮箱核心）
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
    path: '/accounts',
    name: 'accounts',
    icon: 'user',
    component: './accounts',
  },
  {
    path: '/mailbox',
    name: 'mailbox',
    icon: 'mail',
    component: './mailbox',
  },
  {
    path: '/groups',
    name: 'groups',
    icon: 'team',
    component: './groups',
  },
  {
    path: '/',
    redirect: '/accounts',
  },
  {
    path: '*',
    layout: false,
    component: './exception/404',
  },
];
