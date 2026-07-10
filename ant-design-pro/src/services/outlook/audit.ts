import { outlookRequest } from './request';

export type AuditLogItem = {
  id?: number;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  detail?: string;
  details?: string;
  operator?: string;
  ip?: string;
  user_ip?: string;
  trace_id?: string;
  created_at?: string;
  [key: string]: any;
};

export type AuditLogsResponse = {
  success: boolean;
  logs?: AuditLogItem[];
  total?: number;
  limit?: number;
  offset?: number;
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
    params: {
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      action: params.action || undefined,
      resource_type: params.resource_type || undefined,
    },
    skipErrorHandler: true,
  });
}
