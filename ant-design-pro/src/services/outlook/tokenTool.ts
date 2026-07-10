import { outlookRequest } from './request';

export type TokenToolConfig = {
  client_id?: string;
  client_secret?: string;
  redirect_uri?: string;
  scope?: string;
  tenant?: string;
  prompt_consent?: boolean;
  [key: string]: any;
};

export type TokenResult = {
  refresh_token?: string;
  access_token?: string;
  client_id?: string;
  redirect_uri?: string;
  requested_scope?: string;
  granted_scope?: string;
  audience?: string;
  scope_claim?: string;
  roles_claim?: string;
  expires_in?: number | string;
  [key: string]: any;
};

export async function fetchTokenToolConfig() {
  return outlookRequest<{ success: boolean; data?: TokenToolConfig; error?: any }>(
    '/api/token-tool/config',
    { method: 'GET', skipErrorHandler: true },
  );
}

export async function saveTokenToolConfig(config: TokenToolConfig) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    '/api/token-tool/config',
    { method: 'POST', data: config, skipErrorHandler: true },
  );
}

export async function prepareOAuth(config: TokenToolConfig) {
  return outlookRequest<{
    success: boolean;
    data?: { authorize_url?: string };
    error?: any;
  }>('/api/token-tool/prepare', {
    method: 'POST',
    data: config,
    skipErrorHandler: true,
  });
}

export async function exchangeToken(callbackUrl: string) {
  return outlookRequest<{ success: boolean; data?: TokenResult; error?: any }>(
    '/api/token-tool/exchange',
    {
      method: 'POST',
      data: { callback_url: callbackUrl },
      skipErrorHandler: true,
    },
  );
}

export async function fetchTokenToolAccounts() {
  return outlookRequest<{
    success: boolean;
    data?: Array<{ id: number; email: string; status?: string }>;
    error?: any;
  }>('/api/token-tool/accounts', {
    method: 'GET',
    skipErrorHandler: true,
  });
}

export async function saveTokenToAccount(body: {
  mode: 'update' | 'create' | string;
  refresh_token: string;
  client_id?: string;
  account_id?: number | string;
  email?: string;
}) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    '/api/token-tool/save',
    { method: 'POST', data: body, skipErrorHandler: true },
  );
}

export function pickTokenToolError(payload: any, fallback = '请求失败'): string {
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
