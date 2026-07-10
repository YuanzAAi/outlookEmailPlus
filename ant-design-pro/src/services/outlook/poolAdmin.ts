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
  /** 后端真实字段 */
  items?: PoolAccountItem[];
  total?: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
  /** 兼容别名 */
  accounts?: PoolAccountItem[];
  pagination?: {
    page?: number;
    page_size?: number;
    total_count?: number;
    total?: number;
  };
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

/** claimed 账号仅允许 force_release；其余状态用完整动作集 */
export function actionsForPoolRow(row: PoolAccountItem) {
  const status = String(row.pool_status || '').toLowerCase();
  if (status === 'claimed') {
    return [{ label: '强制释放申领', value: 'force_release' }];
  }
  return [
    { label: '移入池', value: 'move_into_pool' },
    { label: '移出池', value: 'move_out_of_pool' },
    { label: '恢复可用', value: 'restore_available' },
    { label: '冻结', value: 'freeze' },
    { label: '退役', value: 'retire' },
    { label: '强制释放申领', value: 'force_release' },
  ];
}

export async function batchPoolAction(
  accountIds: number[],
  action: string,
): Promise<{ ok: number; fail: number; errors: string[] }> {
  let ok = 0;
  let fail = 0;
  const errors: string[] = [];
  for (const id of accountIds) {
    try {
      const res = await applyPoolAction(id, action);
      if (res?.success === false) {
        fail += 1;
        errors.push(`#${id}: ${pickPoolError(res)}`);
      } else {
        ok += 1;
      }
    } catch (e: any) {
      fail += 1;
      errors.push(`#${id}: ${e?.message || '失败'}`);
    }
  }
  return { ok, fail, errors };
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
