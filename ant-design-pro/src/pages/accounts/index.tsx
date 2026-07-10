import {
  DeleteOutlined,
  MailOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { App, Button, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import React, { useMemo, useRef, useState } from 'react';
import {
  deleteAccount,
  fetchAccounts,
  type AccountItem,
} from '@/services/outlook/accounts';
import {
  fetchGroups,
  isTempMailboxGroup,
  type GroupItem,
} from '@/services/outlook/groups';

const statusColor = (status?: string) => {
  const s = String(status || '').toLowerCase();
  if (s === 'active') return 'success';
  if (s === 'expired' || s === 'inactive' || s === 'disabled') return 'default';
  if (s === 'error' || s === 'failed') return 'error';
  return 'processing';
};

const AccountsPage: React.FC = () => {
  const { message } = App.useApp();
  const actionRef = useRef<ActionType>(null);
  const [groupId, setGroupId] = useState<number | undefined>(undefined);

  const groupsQuery = useQuery({
    queryKey: ['groups'],
    queryFn: fetchGroups,
  });

  const groupOptions = useMemo(() => {
    const groups = (groupsQuery.data?.groups || []).filter(
      (g: GroupItem) => !isTempMailboxGroup(g),
    );
    return groups.map((g) => ({
      label: `${g.name} (${g.account_count || 0})`,
      value: g.id,
    }));
  }, [groupsQuery.data]);

  const columns: ProColumns<AccountItem>[] = [
    {
      title: '邮箱',
      dataIndex: 'email',
      copyable: true,
      ellipsis: true,
      fieldProps: { placeholder: '搜索邮箱' },
    },
    {
      title: '分组',
      dataIndex: 'group_name',
      search: false,
      render: (_, row) => (
        <Space size={6}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: row.group_color || '#666',
              display: 'inline-block',
            }}
          />
          {row.group_name || '--'}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      search: false,
      render: (_, row) => (
        <Tag color={statusColor(row.status)}>{row.status || '--'}</Tag>
      ),
    },
    {
      title: '类型',
      dataIndex: 'account_type',
      width: 100,
      search: false,
      render: (_, row) => row.account_type || row.provider || '--',
    },
    {
      title: '备注',
      dataIndex: 'remark',
      ellipsis: true,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '最近刷新',
      dataIndex: 'last_refresh_at',
      width: 180,
      search: false,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>
            {row.last_refresh_at || '--'}
          </Typography.Text>
          {row.last_refresh_status ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {row.last_refresh_status}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      render: (_, row) => [
        <Button
          key="mailbox"
          type="link"
          icon={<MailOutlined />}
          href={`/mailbox?account=${encodeURIComponent(row.email)}`}
        >
          邮件
        </Button>,
        <Popconfirm
          key="delete"
          title="确认删除该账号？"
          onConfirm={async () => {
            try {
              const res = await deleteAccount(row.id);
              if (res?.success === false) {
                message.error(
                  (typeof res.error === 'object' && res.error?.message) ||
                    res.message ||
                    '删除失败',
                );
                return;
              }
              message.success('删除成功');
              actionRef.current?.reload();
            } catch (error: any) {
              message.error(error?.message || '删除失败');
            }
          }}
        >
          <Button type="link" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>,
      ],
    },
  ];

  return (
    <PageContainer
      title="账号管理"
      subTitle="对接 /api/accounts"
      extra={
        <Button
          icon={<ReloadOutlined />}
          onClick={() => actionRef.current?.reload()}
        >
          刷新
        </Button>
      }
    >
      <ProTable<AccountItem>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        cardBordered
        options={{ density: true, reload: true, setting: true }}
        form={{ syncToUrl: false }}
        toolbar={{
          search: false,
          actions: [
            <Select
              key="group"
              allowClear
              placeholder="按分组筛选"
              style={{ width: 220 }}
              options={groupOptions}
              loading={groupsQuery.isLoading}
              value={groupId}
              onChange={(value) => {
                setGroupId(value);
                actionRef.current?.reload();
              }}
            />,
          ],
        }}
        request={async (params) => {
          try {
            const res = await fetchAccounts({
              page: params.current || 1,
              page_size: params.pageSize || 20,
              search: (params.email as string) || undefined,
              group_id: groupId,
              sort_by: 'email',
              sort_order: 'asc',
            });
            return {
              data: res.accounts || [],
              success: !!res.success,
              total: res.pagination?.total_count || 0,
            };
          } catch (error: any) {
            message.error(error?.message || '加载账号失败');
            return { data: [], success: false, total: 0 };
          }
        }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
        }}
      />
    </PageContainer>
  );
};

export default AccountsPage;
