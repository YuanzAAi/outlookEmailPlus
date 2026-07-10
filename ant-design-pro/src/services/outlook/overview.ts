/**
 * 概览 Dashboard API
 */
import { outlookRequest } from './request';

export type OverviewSummary = {
  account_status?: {
    total?: number;
    active?: number;
    expired?: number;
    pending_refresh?: number;
    error?: number;
  };
  pool_snapshot?: {
    available?: number;
    in_use?: number;
    cooldown?: number;
    used?: number;
    disabled?: number;
    total?: number;
    usage_rate?: number;
  };
  refresh_health?: {
    last_run_at?: string | null;
    last_success_count?: number;
    last_fail_count?: number;
    last_duration_s?: number;
    success_rate_7d?: number;
  };
  kpi?: {
    emails_received?: number;
    verification_extracted?: number;
    temp_emails_active?: number;
  };
};

export type OverviewVerification = {
  kpi?: {
    total_count?: number;
    success_count?: number;
    fail_count?: number;
    success_rate?: number;
    ai_used_count?: number;
    ai_success_rate?: number;
    avg_duration_ms?: number;
    p95_duration_ms?: number;
  };
  channel_stats?: Array<{
    channel?: string;
    label?: string;
    count?: number;
    success_count?: number;
    success_rate?: number;
    avg_duration_ms?: number;
  }>;
  recent?: Array<{
    started_at?: number | string;
    account_email?: string;
    channel?: string;
    channel_label?: string;
    code_found?: string;
    duration_ms?: number;
    result_type?: string;
    error_code?: string;
  }>;
};

export type OverviewExternalApi = {
  kpi?: {
    today_calls?: number;
    week_calls?: number;
    today_vs_yesterday_rate?: number;
    success_rate?: number;
    error_count?: number;
    active_callers?: number;
  };
  daily_series?: Array<{ date?: string; count?: number }>;
  caller_rank?: Array<{
    key_name?: string;
    caller_id?: string;
    today_calls?: number;
    week_calls?: number;
    success_rate?: number;
    last_used_at?: string;
  }>;
  by_endpoint?: Array<{
    endpoint?: string;
    count?: number;
    rate?: number;
  }>;
};

export type OverviewPool = {
  kpi?: {
    available?: number;
    in_use?: number;
    cooldown?: number;
    used?: number;
    claim_count_7d?: number;
    complete_success_rate?: number;
    max_claimed_duration_s?: number;
  };
  operation_distribution?: Record<string, number>;
  recent_operations?: Array<Record<string, any>>;
  project_top5?: Array<{
    project_key?: string;
    account_count?: number;
    success_count?: number;
    reuse_rate?: number;
  }>;
};

export type OverviewActivity = {
  kpi?: {
    audit_ops_24h?: number;
    notification_total_24h?: number;
    verification_events_24h?: number;
    [key: string]: number | string | undefined;
  };
  /** 兼容别名 */
  recent?: Array<Record<string, any>>;
  items?: Array<Record<string, any>>;
  by_action?: Array<Record<string, any>>;
  notification_stats?: Record<
    string,
    { count?: number; success_count?: number; success_rate?: number }
  >;
  op_type_dist?: Array<{ action_group?: string; count?: number }>;
  timeline?: Array<{
    time?: string;
    action?: string;
    status?: string;
    resource_type?: string;
    operator?: string;
    channel?: string;
    code_found?: string | boolean | null;
    duration_ms?: number;
    [key: string]: any;
  }>;
  [key: string]: any;
};

export async function fetchOverviewSummary() {
  return outlookRequest<OverviewSummary>('/api/overview/summary', {
    method: 'GET',
  });
}

export async function fetchOverviewVerification() {
  return outlookRequest<OverviewVerification>('/api/overview/verification', {
    method: 'GET',
  });
}

export async function fetchOverviewExternalApi() {
  return outlookRequest<OverviewExternalApi>('/api/overview/external-api', {
    method: 'GET',
  });
}

export async function fetchOverviewPool() {
  return outlookRequest<OverviewPool>('/api/overview/pool', {
    method: 'GET',
  });
}

export async function fetchOverviewActivity() {
  return outlookRequest<OverviewActivity>('/api/overview/activity', {
    method: 'GET',
  });
}
