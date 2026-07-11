/**
 * 轮询等最小设置读取（本 PR 仅保留账号/邮箱所需接口）。
 */
import { outlookRequest } from './request';

export type SettingsMap = Record<string, any>;

export async function fetchSettings(options?: Record<string, any>) {
  return outlookRequest<{
    success?: boolean;
    settings?: SettingsMap;
  }>('/api/settings', {
    method: 'GET',
    ...(options || {}),
  });
}
