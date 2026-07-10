import { ReloadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { App, Button, Select, Space, Tag } from 'antd';
import React, { useMemo, useRef, useState } from 'react';
import { fetchGroups, type GroupItem } from '@/services/outlook/groups';
import {
  applyPoolAction,
  fetchPoolAccounts,
  pickPoolError,
  type PoolAccountItem,
} from '@/services/outlook/poolAdmin';

// 与 outlook_web/services/pool_admin.ACTION_RULES + force_release 对齐
const ACTIONS = [
  { label: '移入池', value: 'move_into_pool' },
  { label: '移出池', value: 'move_out_of_pool' },
  { label: '恢复可用', value: 'restore_available' },
  { label: '冻结', value: 'freeze' },
  { label: '退役', value: 'retire' },
  { label: '强制释放申领', value: 'force_release' },
];

const statusColor = (status?: string) => {
  const s = String(status || '').toLowerCase();
  if (s === 'available' || s === 'ready') return 'success';
  if (s === 'claimed') return 'processing';
  if (s === 'frozen' || s === 'cooldown') return 'warning';
  if (s === 'retired' || s === 'disabled') return 'default';
  return 'default';
};

const PoolAdminPage: React.FC = () => {
  const { message } = App.useApp();
  const actionRef = useRef<ActionType>(null);
  // 后端 in_pool 仅接受 true | false | all（见 pool_admin_repo.list_accounts）
  const [inPool, setInPool] = useState<string>('all');
  const [poolStatus, setPoolStatus] = useState<string | undefined>();
  const [groupId, setGroupId] = useState<number | undefined>();

  const groupsQuery = useQuery({
    queryKey: ['groups'],
    queryFn: fetchGroups,
  });

  const groupOptions = useMemo(
    () =>
      (groupsQuery.data?.groups || []).map((g: GroupItem) => ({
        label: g.name,
        value: g.id,
      })),
    [groupsQuery.data],
  );

  const runAction = async (row: PoolAccountItem, action: string) => {
    try {
      const res = await applyPoolAction(row.id, action);
      if (res?.success === false) {
        message.error(pickPoolError(res, '操作失败'));
        return;
      }
      message.success(res.message || '操作成功');
      actionRef.current?.reload();
    } catch (error: any) {
      message.error(
        pickPoolError(
          error?.data || error?.info || error?.response?.data,
          error?.message || '操作失败',
        ),
      );
    }
  };

  const columns: ProColumns<PoolAccountItem>[] = [
    {
      title: '邮箱',
      dataIndex: 'email',
      copyable: true,
      ellipsis: true,
      fieldProps: { placeholder: '搜索邮箱' },
    },
    {
      title: '池状态',
      dataIndex: 'pool_status',
      width: 120,
      search: false,
      render: (_, row) => (
        <Tag color={statusColor(row.pool_status)}>{row.pool_status || '--'}</Tag>
      ),
    },
    {
      title: '在池',
      dataIndex: 'pool_status',
      width: 80,
      search: false,
      // 后端无 in_pool 字段：pool_status 非空即在池内
      render: (_, row) => (row.pool_status ? '是' : '否'),
    },
    {
      title: '分组',
      dataIndex: 'group_name',
      width: 140,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: 'Provider',
      dataIndex: 'provider',
      width: 120,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '申领者',
      dataIndex: 'claimed_by',
      width: 140,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '操作',
      valueType: 'option',
      width: 220,
      render: (_, row) => (
        <Select
          placeholder="选择动作"
          style={{ width: 180 }}
          options={ACTIONS}
          onChange={(value) => void runAction(row, value)}
        />
      ),
    },
  ];

  return (
    <PageContainer
      title="邮箱池管理"
      subTitle="对接 /api/pool-admin/*"
      extra={
        <Button
          icon={<ReloadOutlined />}
          onClick={() => actionRef.current?.reload()}
        >
          刷新
        </Button>
      }
    >
      <ProTable<PoolAccountItem>
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
              key="in_pool"
              style={{ width: 140 }}
              value={inPool}
              options={[
                { label: '全部', value: 'all' },
                { label: '在池内', value: 'true' },
                { label: '不在池', value: 'false' },
              ]}
              onChange={(v) => {
                setInPool(v);
                actionRef.current?.reload();
              }}
            />,
            <Select
              key="status"
              allowClear
              placeholder="池状态"
              style={{ width: 140 }}
              value={poolStatus}
              options={[
                { label: 'available', value: 'available' },
                { label: 'claimed', value: 'claimed' },
                { label: 'frozen', value: 'frozen' },
                { label: 'cooldown', value: 'cooldown' },
                { label: 'retired', value: 'retired' },
              ]}
              onChange={(v) => {
                setPoolStatus(v);
                actionRef.current?.reload();
              }}
            />,
            <Select
              key="group"
              allowClear
              placeholder="分组"
              style={{ width: 180 }}
              options={groupOptions}
              loading={groupsQuery.isLoading}
              value={groupId}
              onChange={(v) => {
                setGroupId(v);
                actionRef.current?.reload();
              }}
            />,
          ],
        }}
        request={async (params) => {
          try {
            const res = await fetchPoolAccounts({
              page: params.current || 1,
              page_size: params.pageSize || 50,
              search: (params.email as string) || undefined,
              in_pool: inPool,
              pool_status: poolStatus,
              group_id: groupId,
            });
            // 后端形状：{ items, total, page, page_size, total_pages }
            const list = res.items || res.accounts || [];
            const total =
              res.total ??
              res.pagination?.total_count ??
              res.pagination?.total ??
              list.length;
            return {
              data: list,
              success: res.success !== false,
              total,
            };
          } catch (error: any) {
            message.error(error?.message || '加载邮箱池失败');
            return { data: [], success: false, total: 0 };
          }
        }}
        pagination={{ defaultPageSize: 50, showSizeChanger: true }}
        headerTitle={
          <Space>
            <span>池账号</span>
          </Space>
        }
      />
    </PageContainer>
  );
};

export default PoolAdminPage;
