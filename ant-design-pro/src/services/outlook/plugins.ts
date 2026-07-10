import { outlookRequest } from './request';

export type PluginItem = {
  name: string;
  display_name?: string;
  description?: string;
  author?: string;
  version?: string;
  min_app_version?: string;
  status?: 'installed' | 'available' | 'load_failed' | string;
  error?: string;
  download_url?: string;
  dependencies?: string[];
  [key: string]: any;
};

export type PluginsListResponse = {
  success: boolean;
  code?: string;
  message?: string;
  data?: {
    plugins: PluginItem[];
    installed_count?: number;
  };
  error?: any;
};

export type PluginConfigSchema = {
  fields?: Array<{
    key: string;
    label?: string;
    type?: string;
    required?: boolean;
    placeholder?: string;
    description?: string;
    default?: any;
    [key: string]: any;
  }>;
  [key: string]: any;
};

export async function fetchPlugins() {
  return outlookRequest<PluginsListResponse>('/api/plugins', {
    method: 'GET',
    skipErrorHandler: true,
  });
}

export async function installPlugin(body: { name: string; url?: string }) {
  return outlookRequest<{ success: boolean; message?: string; data?: any; error?: any }>(
    '/api/plugins/install',
    {
      method: 'POST',
      data: body,
      skipErrorHandler: true,
    },
  );
}

export async function uninstallPlugin(name: string, cleanConfig = false) {
  return outlookRequest<{ success: boolean; message?: string; data?: any; error?: any }>(
    `/api/plugins/${encodeURIComponent(name)}/uninstall`,
    {
      method: 'POST',
      data: { clean_config: cleanConfig },
      skipErrorHandler: true,
    },
  );
}

export async function fetchPluginConfigSchema(name: string) {
  return outlookRequest<{ success: boolean; data?: PluginConfigSchema; error?: any }>(
    `/api/plugins/${encodeURIComponent(name)}/config/schema`,
    { method: 'GET', skipErrorHandler: true },
  );
}

export async function fetchPluginConfig(name: string) {
  return outlookRequest<{ success: boolean; data?: Record<string, any>; error?: any }>(
    `/api/plugins/${encodeURIComponent(name)}/config`,
    { method: 'GET', skipErrorHandler: true },
  );
}

export async function savePluginConfig(name: string, config: Record<string, any>) {
  return outlookRequest<{ success: boolean; message?: string; data?: any; error?: any }>(
    `/api/plugins/${encodeURIComponent(name)}/config`,
    {
      method: 'POST',
      data: { config },
      skipErrorHandler: true,
    },
  );
}

export async function testPluginConnection(name: string) {
  return outlookRequest<{ success: boolean; message?: string; data?: any; error?: any }>(
    `/api/plugins/${encodeURIComponent(name)}/test-connection`,
    {
      method: 'POST',
      data: {},
      skipErrorHandler: true,
    },
  );
}

export async function reloadPlugins() {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    '/api/system/reload-plugins',
    {
      method: 'POST',
      data: {},
      skipErrorHandler: true,
    },
  );
}

export function pickPluginErrorMessage(payload: any, fallback = '请求失败'): string {
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
