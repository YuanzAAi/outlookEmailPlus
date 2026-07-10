import type { ProLayoutProps } from '@ant-design/pro-components';

/**
 * OutlookEmail 前端布局默认设置
 */
const Settings: ProLayoutProps & {
  logo?: string;
} = {
  navTheme: 'light',
  colorPrimary: '#B85C38',
  layout: 'mix',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  colorWeak: false,
  title: 'Outlook 邮件管理',
  logo: '/img/ico.png',
  iconfontUrl: '',
  token: {
    // https://procomponents.ant.design/components/layout#%E9%80%9A%E8%BF%87-token-%E4%BF%AE%E6%94%B9%E6%A0%B7%E5%BC%8F
  },
};

export default Settings;
