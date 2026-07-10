import { outlookRequest } from './request';

export type GroupItem = {
  id: number;
  name: string;
  description?: string | null;
  color?: string | null;
  is_system?: number;
  account_count?: number;
  proxy_url?: string | null;
  created_at?: string;
  verification_code_length?: string;
  verification_code_regex?: string;
};

export type GroupsResponse = {
  success: boolean;
  groups: GroupItem[];
};

export async function fetchGroups() {
  return outlookRequest<GroupsResponse>('/api/groups', { method: 'GET' });
}

export async function createGroup(body: {
  name: string;
  description?: string;
  color?: string;
  proxy_url?: string;
  verification_code_length?: string;
  verification_code_regex?: string;
}) {
  return outlookRequest<{
    success: boolean;
    message?: string;
    group_id?: number;
    error?: any;
  }>('/api/groups', {
    method: 'POST',
    data: body,
  });
}

export async function updateGroup(
  groupId: number,
  body: {
    name: string;
    description?: string;
    color?: string;
    proxy_url?: string;
    verification_code_length?: string;
    verification_code_regex?: string;
  },
) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    `/api/groups/${groupId}`,
    {
      method: 'PUT',
      data: body,
    },
  );
}

export async function deleteGroup(groupId: number) {
  return outlookRequest<{ success: boolean; message?: string; error?: any }>(
    `/api/groups/${groupId}`,
    {
      method: 'DELETE',
    },
  );
}

export function isTempMailboxGroup(group?: Pick<GroupItem, 'name' | 'is_system'> | null) {
  if (!group) return false;
  return group.name === '临时邮箱' || Number(group.is_system) === 1;
}
