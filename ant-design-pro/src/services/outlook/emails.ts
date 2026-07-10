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

/** 将后端 method 展示名映射为请求参数 */
export function normalizeMethodParam(method?: string): EmailMethod {
  const m = String(method || '').toLowerCase();
  if (m.includes('graph')) return 'graph';
  if (m.includes('imap')) return 'imap';
  return m || 'graph';
}

export function pickEmailsErrorMessage(payload: any, fallback = '获取邮件失败'): string {
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
  if (typeof payload.message === 'string' && payload.message) return payload.message;
  return fallback;
}
