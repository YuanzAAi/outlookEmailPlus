import { outlookRequest } from './request';

export type EmailFolder = 'inbox' | 'junkemail' | 'deleteditems' | string;

export type EmailMethod = 'graph' | 'imap' | string;

export type EmailListItem = {
  id: string;
  subject?: string;
  from?: string;
  date?: string;
  is_read?: boolean;
  has_attachments?: boolean;
  body_preview?: string;
};

export type EmailDetail = {
  id?: string;
  subject?: string;
  from?: string;
  to?: string;
  cc?: string;
  date?: string;
  body?: string;
  body_type?: 'html' | 'text' | string;
  inline_resources?: Record<string, string>;
};

export type EmailsListResponse = {
  success: boolean;
  emails?: EmailListItem[];
  method?: string;
  has_more?: boolean;
  account_summary?: Record<string, any>;
  error?: any;
  details?: any;
  message?: string;
};

export type EmailDetailResponse = {
  success: boolean;
  email?: EmailDetail;
  error?: any;
  message?: string;
};

export type FetchEmailsParams = {
  method?: EmailMethod;
  folder?: EmailFolder;
  skip?: number;
  top?: number;
};

export async function fetchEmails(email: string, params: FetchEmailsParams = {}) {
  const encoded = encodeURIComponent(email);
  return outlookRequest<EmailsListResponse>(`/api/emails/${encoded}`, {
    method: 'GET',
    params: {
      method: params.method || 'graph',
      folder: params.folder || 'inbox',
      skip: params.skip ?? 0,
      top: params.top ?? 20,
    },
    // 502 / 401 业务失败也要拿到 body，交给页面展示 details
    skipErrorHandler: true,
    getResponse: false,
  });
}

export async function fetchEmailDetail(
  email: string,
  messageId: string,
  params: { method?: EmailMethod; folder?: EmailFolder } = {},
) {
  const encodedEmail = encodeURIComponent(email);
  const encodedId = encodeURIComponent(messageId);
  return outlookRequest<EmailDetailResponse>(
    `/api/email/${encodedEmail}/${encodedId}`,
    {
      method: 'GET',
      params: {
        method: params.method || 'graph',
        folder: params.folder || 'inbox',
      },
      skipErrorHandler: true,
    },
  );
}

export async function deleteEmails(email: string, ids: string[]) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    '/api/emails/delete',
    {
      method: 'POST',
      data: { email, ids },
      skipErrorHandler: true,
    },
  );
}

export type VerificationExtractData = {
  verification_code?: string;
  verification_link?: string;
  formatted?: string;
  code?: string;
  [key: string]: any;
};

export async function extractEmailVerification(
  email: string,
  params: {
    code_length?: string;
    code_regex?: string;
    code_source?: 'subject' | 'content' | 'html' | 'all';
  } = {},
) {
  return outlookRequest<{
    success: boolean;
    data?: VerificationExtractData;
    message?: string;
    account_summary?: Record<string, any>;
    error?: any;
  }>(`/api/emails/${encodeURIComponent(email)}/extract-verification`, {
    method: 'GET',
    params: {
      code_length: params.code_length,
      code_regex: params.code_regex,
      code_source: params.code_source || 'all',
    },
    skipErrorHandler: true,
  });
}

/** 将后端 method 展示名映射为请求参数 */
export function normalizeMethodParam(method?: string): EmailMethod {
  const m = String(method || '').toLowerCase();
  if (m.includes('graph')) return 'graph';
  if (m.includes('imap')) return 'imap';
  return m || 'graph';
}

/** 将常见后端错误码/英文文案映射为可读中文 */
function humanizeEmailError(raw: string): string {
  const text = String(raw || '').trim();
  if (!text) return '';
  const lower = text.toLowerCase();
  if (
    lower.includes('token') &&
    (lower.includes('expir') || lower.includes('invalid') || lower.includes('refresh'))
  ) {
    return '授权已过期或令牌无效，请重新授权后再试';
  }
  if (
    lower.includes('unauthorized') ||
    lower.includes('401') ||
    lower.includes('auth')
  ) {
    return '授权失败，请检查账号授权或重新登录';
  }
  if (
    lower.includes('get_token') ||
    lower.includes('fetch token') ||
    lower.includes('obtain token') ||
    lower.includes('access_token')
  ) {
    return '获取访问令牌失败，请检查账号配置或重新授权';
  }
  if (lower.includes('proxy') || lower.includes('tunnel')) {
    return '代理连接失败，请检查代理设置';
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return '请求超时，请稍后重试';
  }
  if (lower.includes('network') || lower.includes('econnrefused')) {
    return '网络连接失败，请检查网络后重试';
  }
  // 已是中文则直接返回
  if (/[\u4e00-\u9fff]/.test(text)) return text;
  return text;
}

export function pickEmailsErrorMessage(payload: any, fallback = '获取邮件失败'): string {
  if (!payload) return fallback;
  let raw = '';
  if (typeof payload.error === 'string' && payload.error) raw = payload.error;
  else if (payload.error && typeof payload.error === 'object') {
    raw =
      payload.error.message ||
      payload.error.message_zh ||
      payload.error.message_en ||
      payload.error.code ||
      '';
  } else if (typeof payload.message === 'string' && payload.message) {
    raw = payload.message;
  }
  return humanizeEmailError(raw) || fallback;
}
