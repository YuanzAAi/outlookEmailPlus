import { outlookRequest } from './request';

export type AccountItem = {
  id: number;
  email: string;
  account_type?: string;
  provider?: string;
  client_id?: string;
  group_id?: number | null;
  group_name?: string;
  group_color?: string;
  remark?: string | null;
  status?: string;
  tags?: Array<{ id?: number; name?: string; color?: string } | string>;
  notification_enabled?: boolean;
  telegram_push_enabled?: boolean;
  last_refresh_at?: string | null;
  last_refresh_status?: string | null;
  last_refresh_error?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type AccountsResponse = {
  success: boolean;
  accounts: AccountItem[];
  pagination?: {
    page: number;
    page_size: number;
    total_count: number;
    total_pages: number;
  };
};

export type AccountListParams = {
  group_id?: number;
  page?: number;
  page_size?: number;
  search?: string;
  sort_by?: 'refresh_time' | 'email';
  sort_order?: 'asc' | 'desc';
  tag_id?: number | number[];
};

export async function fetchAccounts(params: AccountListParams = {}) {
  return outlookRequest<AccountsResponse>('/api/accounts', {
    method: 'GET',
    params,
  });
}

export async function deleteAccount(accountId: number) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    `/api/accounts/${accountId}`,
    { method: 'DELETE' },
  );
}

export async function updateAccountRemark(accountId: number, remark: string) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    `/api/accounts/${accountId}/remark`,
    {
      method: 'PATCH',
      data: { remark },
    },
  );
}

export async function createAccount(body: Record<string, any>) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    message_en?: string;
    summary?: Record<string, any>;
    errors?: Array<Record<string, any>>;
    error?: any;
    [key: string]: any;
  }>('/api/accounts', {
    method: 'POST',
    data: body,
    skipErrorHandler: true,
  });
}

export async function fetchAccount(accountId: number) {
  return outlookRequest<{
    success: boolean;
    account?: AccountItem & {
      password?: string;
      client_id?: string;
      refresh_token?: string;
      has_password?: boolean;
      has_refresh_token?: boolean;
    };
    error?: any;
  }>(`/api/accounts/${accountId}`, {
    method: 'GET',
    skipErrorHandler: true,
  });
}

export async function updateAccount(
  accountId: number,
  body: Record<string, any>,
) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    message_en?: string;
    error?: any;
  }>(`/api/accounts/${accountId}`, {
    method: 'PUT',
    data: body,
    skipErrorHandler: true,
  });
}

export type ProviderItem = {
  key: string;
  label: string;
  account_type?: string;
  note?: string;
};

export async function fetchProviders() {
  return outlookRequest<{ success: boolean; providers?: ProviderItem[] }>(
    '/api/providers',
    { method: 'GET', skipErrorHandler: true },
  );
}

export function pickAccountErrorMessage(
  payload: any,
  fallback = '请求失败',
): string {
  if (!payload) return fallback;
  if (typeof payload.error === 'string' && payload.error) return payload.error;
  if (payload.error && typeof payload.error === 'object') {
    return (
      payload.error.message ||
      payload.error.message_en ||
      payload.error.code ||
      fallback
    );
  }
  if (typeof payload.message === 'string' && payload.message) {
    return payload.message;
  }
  if (Array.isArray(payload.errors) && payload.errors.length) {
    const first = payload.errors[0];
    const detail =
      typeof first === 'string'
        ? first
        : first?.error || first?.message || JSON.stringify(first);
    return `导入部分失败：${detail}`;
  }
  return fallback;
}

export async function batchUpdateAccountStatus(
  accountIds: number[],
  status: string,
) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    updated_count?: number;
    failed_count?: number;
    error?: any;
  }>('/api/accounts/batch-update-status', {
    method: 'POST',
    data: { account_ids: accountIds, status },
    skipErrorHandler: true,
  });
}

export async function batchDeleteAccounts(accountIds: number[]) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    deleted_count?: number;
    error?: any;
  }>('/api/accounts/batch-delete', {
    method: 'POST',
    data: { account_ids: accountIds },
    skipErrorHandler: true,
  });
}

export async function batchUpdateAccountGroup(
  accountIds: number[],
  groupId: number,
) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    error?: any;
  }>('/api/accounts/batch-update-group', {
    method: 'POST',
    data: { account_ids: accountIds, group_id: groupId },
    skipErrorHandler: true,
  });
}

export async function batchNotificationToggle(
  accountIds: number[],
  enabled: boolean,
) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    error?: any;
  }>('/api/accounts/batch-notification-toggle', {
    method: 'POST',
    data: { account_ids: accountIds, enabled },
    skipErrorHandler: true,
  });
}

export async function toggleAccountTelegram(
  accountId: number,
  enabled: boolean,
) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    error?: any;
  }>(`/api/accounts/${accountId}/telegram-toggle`, {
    method: 'POST',
    data: { enabled },
    skipErrorHandler: true,
  });
}

export async function refreshSelectedAccounts(accountIds: number[]) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    error?: any;
  }>('/api/accounts/refresh/selected', {
    method: 'POST',
    data: { account_ids: accountIds },
    skipErrorHandler: true,
  });
}

export async function verifyExportPassword(password: string) {
  return outlookRequest<{
    success: boolean;
    verify_token?: string;
    message?: string;
    error?: any;
  }>('/api/export/verify', {
    method: 'POST',
    data: { password },
    skipErrorHandler: true,
  });
}

/** 导出选中分组（blob）；需先 verifyExportPassword 拿 token */
export async function exportSelectedGroups(
  groupIds: number[],
  verifyToken: string,
): Promise<{ blob: Blob; filename: string }> {
  const res = await outlookRequest<any>('/api/accounts/export-selected', {
    method: 'POST',
    data: { group_ids: groupIds },
    headers: { 'X-Export-Token': verifyToken },
    skipErrorHandler: true,
    getResponse: true,
    responseType: 'blob',
  } as any);

  // umi request getResponse: true → { data, response }
  const response: Response | undefined = res?.response;
  const data = res?.data ?? res;
  if (response && !response.ok) {
    // blob 错误体尝试解析
    let payload: any = null;
    try {
      const text = await (data as Blob).text();
      payload = JSON.parse(text);
    } catch {
      /* ignore */
    }
    throw new Error(pickAccountErrorMessage(payload, '导出失败'));
  }
  const blob: Blob =
    data instanceof Blob ? data : new Blob([data], { type: 'text/plain' });
  let filename = `accounts_export_${Date.now()}.txt`;
  const cd = response?.headers?.get?.('Content-Disposition') || '';
  const match = cd.match(/filename\*?=(?:UTF-8'')?([^;\n]+)/i);
  if (match) {
    try {
      filename = decodeURIComponent(match[1].replace(/"/g, ''));
    } catch {
      filename = match[1].replace(/"/g, '');
    }
  }
  return { blob, filename };
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}
