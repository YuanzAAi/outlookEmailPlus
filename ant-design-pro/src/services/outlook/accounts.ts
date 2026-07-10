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
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    '/api/accounts',
    {
      method: 'POST',
      data: body,
    },
  );
}
