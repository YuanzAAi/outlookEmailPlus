/** 业务状态枚举 → 中文展示（小映射，避免页面硬编码散落） */

const ACCOUNT_STATUS: Record<string, string> = {
  active: '正常',
  inactive: '停用',
  expired: '已过期',
  error: '异常',
  failed: '失败',
  disabled: '已禁用',
  pending: '待处理',
};

const REFRESH_STATUS: Record<string, string> = {
  success: '成功',
  failed: '失败',
  error: '失败',
  pending: '进行中',
  running: '进行中',
  skipped: '已跳过',
};

const POOL_STATUS: Record<string, string> = {
  available: '可用',
  ready: '就绪',
  claimed: '已申领',
  frozen: '已冻结',
  cooldown: '冷却中',
  retired: '已退役',
  disabled: '已禁用',
};

const PROVIDER_LABEL: Record<string, string> = {
  outlook: 'Outlook',
  imap_generic: 'IMAP',
  custom: '自定义',
};

function mapLabel(dict: Record<string, string>, raw?: string | null): string {
  if (raw == null || raw === '') return '--';
  const key = String(raw).toLowerCase();
  return dict[key] || String(raw);
}

export function accountStatusLabel(status?: string | null): string {
  return mapLabel(ACCOUNT_STATUS, status);
}

export function refreshStatusLabel(status?: string | null): string {
  return mapLabel(REFRESH_STATUS, status);
}

export function poolStatusLabel(status?: string | null): string {
  return mapLabel(POOL_STATUS, status);
}

export function providerLabel(provider?: string | null): string {
  return mapLabel(PROVIDER_LABEL, provider);
}

export const ACCOUNT_STATUS_OPTIONS = [
  { label: '正常', value: 'active' },
  { label: '停用', value: 'inactive' },
  { label: '已过期', value: 'expired' },
  { label: '异常', value: 'error' },
];

export const POOL_STATUS_FILTER_OPTIONS = [
  { label: '可用', value: 'available' },
  { label: '已申领', value: 'claimed' },
  { label: '已冻结', value: 'frozen' },
  { label: '冷却中', value: 'cooldown' },
  { label: '已退役', value: 'retired' },
];

export const PROVIDER_FILTER_OPTIONS = [
  { label: 'Outlook', value: 'outlook' },
  { label: 'IMAP', value: 'imap_generic' },
  { label: '自定义', value: 'custom' },
];
