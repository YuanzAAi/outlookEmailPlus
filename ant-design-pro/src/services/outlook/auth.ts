/**
 * OutlookEmail 鉴权服务 —— 对接 Flask session + CSRF。
 * 不走 openapi 生成目录，业务手写维护。
 */
import { request } from '@umijs/max';

export type OutlookCurrentUser = {
  name?: string;
  userid?: string;
  access?: string;
  avatar?: string;
  title?: string;
  email?: string;
};

export type OutlookLoginResult = {
  success: boolean;
  message?: string;
  status?: 'ok' | 'error';
  error?: {
    code?: string;
    message?: string;
    message_en?: string;
  };
  need_login?: boolean;
};

export type OutlookApiResult<T = unknown> = {
  success: boolean;
  data?: T;
  message?: string;
  error?: {
    code?: string;
    message?: string;
    message_en?: string;
  };
  need_login?: boolean;
};

let csrfTokenCache: string | null = null;
let csrfRefreshPromise: Promise<string | null> | null = null;

type CsrfTokenPayload = {
  csrf_token?: string | null;
  csrf_disabled?: boolean;
};

/** 获取 / 刷新 CSRF Token（与旧前端 main.js 行为对齐） */
export async function ensureCsrfToken(force = false): Promise<string | null> {
  if (!force && csrfTokenCache) {
    return csrfTokenCache;
  }
  if (!force && csrfRefreshPromise) {
    return csrfRefreshPromise;
  }

  csrfRefreshPromise = (async () => {
    try {
      const response = (await request<CsrfTokenPayload>('/api/csrf-token', {
        method: 'GET',
        skipErrorHandler: true,
        credentials: 'include',
      } as any)) as unknown as CsrfTokenPayload | { data?: CsrfTokenPayload };
      const data =
        ((response as { data?: CsrfTokenPayload }).data ??
          response) as CsrfTokenPayload;

      if (data?.csrf_disabled) {
        csrfTokenCache = null;
        return null;
      }
      csrfTokenCache = data?.csrf_token || null;
      return csrfTokenCache;
    } catch {
      csrfTokenCache = null;
      return null;
    } finally {
      csrfRefreshPromise = null;
    }
  })();

  return csrfRefreshPromise;
}

export function clearCsrfToken() {
  csrfTokenCache = null;
}

/** 当前用户 GET /api/auth/current-user */
export async function currentUser(options?: Record<string, any>) {
  return request<OutlookApiResult<OutlookCurrentUser>>(
    '/api/auth/current-user',
    {
      method: 'GET',
      credentials: 'include',
      ...(options || {}),
    },
  );
}

/**
 * 登录 POST /login
 * 后端期望 { password }；为兼容 Pro 表单字段，同时接受 username（忽略）。
 */
export async function login(
  body: { password?: string; username?: string; type?: string },
  options?: Record<string, any>,
) {
  const password = body.password || '';
  const res = await request<OutlookLoginResult>('/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    data: { password },
    credentials: 'include',
    skipErrorHandler: true,
    ...(options || {}),
  });

  // 归一化为 Pro 登录页习惯的 status 字段
  if (res?.success) {
    clearCsrfToken();
    await ensureCsrfToken(true);
    return { ...res, status: 'ok' as const, type: body.type || 'account' };
  }
  return {
    ...res,
    status: 'error' as const,
    type: body.type || 'account',
  };
}

/** 退出登录 POST /api/auth/logout */
export async function outLogin(options?: Record<string, any>) {
  try {
    const token = await ensureCsrfToken();
    const headers: Record<string, string> = {
      Accept: 'application/json',
    };
    if (token) {
      headers['X-CSRFToken'] = token;
    }
    return await request<OutlookApiResult>('/api/auth/logout', {
      method: 'POST',
      headers,
      credentials: 'include',
      skipErrorHandler: true,
      ...(options || {}),
    });
  } finally {
    clearCsrfToken();
  }
}
