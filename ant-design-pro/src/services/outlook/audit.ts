import { outlookRequest } from './request';

export type AuditLogItem = {
  id?: number | string;
  created_at?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string | number;
  /** 后端真实字段 */
  details?: string | Record<string, any> | null;
  user_ip?: string | null;
  trace_id?: string | null;
  /** 兼容别名（若旧响应存在） */
  detail?: string | null;
  ip?: string | null;
  operator?: string | null;
};

export type AuditLogsResponse = {
  success?: boolean;
  logs?: AuditLogItem[];
  total?: number;
  error?: any;
};

export async function fetchAuditLogs(params: {
  limit?: number;
  offset?: number;
  action?: string;
  resource_type?: string;
} = {}) {
  return outlookRequest<AuditLogsResponse>('/api/audit-logs', {
    method: 'GET',
    params,
    skipErrorHandler: true,
  });
}
