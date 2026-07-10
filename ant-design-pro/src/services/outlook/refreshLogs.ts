import { outlookRequest } from './request';

export type RefreshLogItem = {
  id?: number | string;
  created_at?: string;
  /** 后端真实字段 */
  account_email?: string;
  email?: string;
  status?: string;
  error_message?: string | null;
  message?: string | null;
  error?: string | null;
  [key: string]: any;
};

export type RefreshLogsResponse = {
  success?: boolean;
  logs?: RefreshLogItem[];
  total?: number;
  error?: any;
};

export async function fetchRefreshLogs(params: { limit?: number } = {}) {
  return outlookRequest<RefreshLogsResponse>('/api/refresh-logs', {
    method: 'GET',
    params,
    skipErrorHandler: true,
  });
}

export async function fetchFailedRefreshLogs(params: { limit?: number } = {}) {
  return outlookRequest<RefreshLogsResponse>('/api/refresh-logs/failed', {
    method: 'GET',
    params,
    skipErrorHandler: true,
  });
}
