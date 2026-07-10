import { outlookRequest } from './request';

export type RefreshLogItem = {
  id?: number;
  account_id?: number;
  email?: string;
  status?: string;
  message?: string;
  error?: string;
  created_at?: string;
  [key: string]: any;
};

export async function fetchRefreshLogs(params: { limit?: number } = {}) {
  return outlookRequest<{ success?: boolean; logs?: RefreshLogItem[]; error?: any }>(
    '/api/accounts/refresh-logs',
    {
      method: 'GET',
      params: { limit: params.limit ?? 200 },
      skipErrorHandler: true,
    },
  );
}

export async function fetchFailedRefreshLogs() {
  return outlookRequest<{ success?: boolean; logs?: RefreshLogItem[]; error?: any }>(
    '/api/accounts/refresh-logs/failed',
    { method: 'GET', skipErrorHandler: true },
  );
}

export async function fetchRefreshStats() {
  return outlookRequest<{ success?: boolean; [key: string]: any }>(
    '/api/accounts/refresh-stats',
    { method: 'GET', skipErrorHandler: true },
  );
}
