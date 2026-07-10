/**
 * 统一业务请求封装：自动带 credentials + CSRF。
 */
import { request as umiRequest } from '@umijs/max';
import { ensureCsrfToken, clearCsrfToken } from './auth';

type RequestOptions = Record<string, any>;

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function pickErrorMessage(payload: any, fallback = '请求失败'): string {
  if (!payload) return fallback;
  if (typeof payload.error === 'string') return payload.error;
  if (payload.error && typeof payload.error === 'object') {
    return (
      payload.error.message ||
      payload.error.message_en ||
      payload.error.code ||
      fallback
    );
  }
  if (typeof payload.message === 'string') return payload.message;
  return fallback;
}

/**
 * 业务 API 请求。默认 credentials: include。
 * 写操作自动附加 X-CSRFToken；若 400 且像 CSRF 失败会强制刷新后重试一次。
 */
export async function outlookRequest<T = any>(
  url: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = String(options.method || 'GET').toUpperCase();
  const headers: Record<string, string> = {
    ...(options.headers || {}),
  };

  if (MUTATING.has(method)) {
    const token = await ensureCsrfToken();
    if (token) {
      headers['X-CSRFToken'] = token;
    }
  }

  const finalOptions: RequestOptions = {
    ...options,
    method,
    headers,
    credentials: 'include',
  };

  try {
    return await umiRequest<T>(url, finalOptions);
  } catch (error: any) {
    const status = error?.response?.status;
    const data = error?.response?.data;
    const msg = pickErrorMessage(data, error?.message || '');
    const looksLikeCsrf =
      status === 400 &&
      MUTATING.has(method) &&
      /csrf|CSRF|token/i.test(String(msg));

    if (looksLikeCsrf) {
      clearCsrfToken();
      const token = await ensureCsrfToken(true);
      if (token) {
        headers['X-CSRFToken'] = token;
      }
      return umiRequest<T>(url, { ...finalOptions, headers });
    }

    // 业务页常用 skipErrorHandler：把 HTTP 错误体规范化后抛出，
    // 保证 catch 侧总能读到 payload（含 502 details）。
    if (data && typeof data === 'object') {
      const normalized: any = new Error(msg || error?.message || '请求失败');
      normalized.name = error?.name || 'RequestError';
      normalized.response = error?.response;
      normalized.data = data;
      normalized.info = data;
      normalized.status = status;
      throw normalized;
    }
    throw error;
  }
}

export { pickErrorMessage };
