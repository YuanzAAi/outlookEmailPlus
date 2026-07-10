import { outlookRequest } from './request';

export type PoolAccountItem = {
  id: number;
  email?: string;
  pool_status?: string;
  in_pool?: boolean | number;
  provider?: string;
  group_id?: number | null;
  group_name?: string;
  claimed_by?: string | null;
  claimed_at?: string | null;
  cooldown_until?: string | null;
  [key: string]: any;
};

export type PoolAccountsResponse = {
  success?: boolean;
  accounts?: PoolAccountItem[];
  items?: PoolAccountItem[];
  pagination?: {
    page?: number;
    page_size?: number;
    total_count?: number;
    total?: number;
  };
  total?: number;
  error?: any;
  message?: string;
};

export type PoolListParams = {
  in_pool?: string;
  pool_status?: string;
  provider?: string;
  group_id?: number;
  search?: string;
  page?: number;
  page_size?: number;
};

export async function fetchPoolAccounts(params: PoolListParams = {}) {
  return outlookRequest<PoolAccountsResponse>('/api/pool-admin/accounts', {
    method: 'GET',
    params,
    skipErrorHandler: true,
  });
}

export async function applyPoolAction(accountId: number, action: string) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    error_code?: string;
    data?: any;
  }>(`/api/pool-admin/accounts/${accountId}/action`, {
    method: 'POST',
    data: { action },
    skipErrorHandler: true,
  });
}

export function pickPoolError(payload: any, fallback = '请求失败'): string {
  if (!payload) return fallback;
  if (typeof payload.message === 'string' && payload.message) return payload.message;
  if (typeof payload.error === 'string' && payload.error) return payload.error;
  if (payload.error && typeof payload.error === 'object') {
    return payload.error.message || payload.error.code || fallback;
  }
  if (payload.error_code) return String(payload.error_code);
  return fallback;
}
