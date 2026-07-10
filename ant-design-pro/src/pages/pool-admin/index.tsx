import { ReloadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { useIntl } from '@umijs/max';
import { App, Button, Select, Space, Tag } from 'antd';
import React, { useMemo, useRef, useState } from 'react';
import { fetchGroups, type GroupItem } from '@/services/outlook/groups';
import {
  actionsForPoolRow,
  applyPoolAction,
  batchPoolAction,
  fetchPoolAccounts,
  pickPoolError,
  type PoolAccountItem,
} from '@/services/outlook/poolAdmin';
import {
  POOL_STATUS_FILTER_OPTIONS,
  PROVIDER_FILTER_OPTIONS,
  poolStatusLabel,
  providerLabel,
} from '@/utils/statusLabels';

const statusColor = (status?: string) => {
  const s = String(status || '').toLowerCase();
  if (s === 'available' || s === 'ready') return 'success';
  if (s === 'claimed') return 'processing';
  if (s === 'frozen' || s === 'cooldown') return 'warning';
  if (s === 'retired' || s === 'disabled') return 'default';
  return 'default';
};

const BATCH_ACTIONS = [
  { label: '移入池', value: 'move_into_pool' },
  { label: '移出池', value: 'move_out_of_pool' },
  { label: '恢复可用', value: 'restore_available' },
  { label: '冻结', value: 'freeze' },
  { label: '退役', value: 'retire' },
  { label: '强制释放申领', value: 'force_release' },
];

const PoolAdminPage: React.FC = () => {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const actionRef = useRef<ActionType>(null);
  // 后端 in_pool 仅接受 true | false | all（见 pool_admin_repo.list_accounts）
  const [inPool, setInPool] = useState<string>('all');
  const [poolStatus, setPoolStatus] = useState<string | undefined>();
  const [groupId, setGroupId] = useState<number | undefined>();
  const [provider, setProvider] = useState<string | undefined>();
  const [selectedRows, setSelectedRows] = useState<PoolAccountItem[]>([]);

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

  const selectedIds = selectedRows.map((r) => r.id);

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

  const runBatch = (action: string) => {
    if (!selectedIds.length) {
      message.warning('请先勾选账号');
      return;
    }
    const claimedOnlyForce = selectedRows.some(
      (r) =>
        String(r.pool_status || '').toLowerCase() === 'claimed' &&
        action !== 'force_release',
    );
    if (claimedOnlyForce) {
      message.warning(
        '选中项含「已申领」账号：已申领状态仅允许「强制释放申领」，请改选或筛选后重试',
      );
      return;
    }
    const label =
      BATCH_ACTIONS.find((a) => a.value === action)?.label || action;
    modal.confirm({
      title: `对选中 ${selectedIds.length} 项执行「${label}」？`,
      content: '部分账号可能失败，结果会汇总提示',
      onOk: async () => {
        const result = await batchPoolAction(selectedIds, action);
        if (result.fail === 0) {
          message.success(`全部成功（${result.ok}）`);
        } else {
          message.warning(
            `成功 ${result.ok} / 失败 ${result.fail}${
              result.errors[0] ? `：${result.errors[0]}` : ''
            }`,
          );
        }
        setSelectedRows([]);
        actionRef.current?.reload();
      },
    });
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
        <Tag color={statusColor(row.pool_status)}>
          {poolStatusLabel(row.pool_status)}
        </Tag>
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
      title: '来源',
      dataIndex: 'provider',
      width: 120,
      search: false,
      render: (_, row) => providerLabel(row.provider),
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
          options={actionsForPoolRow(row)}
          onChange={(value) => void runAction(row, value)}
        />
      ),
    },
  ];

  return (
    <PageContainer
      title={intl.formatMessage({
        id: 'outlook.pool.title',
        defaultMessage: '邮箱池管理',
      })}
      subTitle={intl.formatMessage({
        id: 'outlook.pool.subtitle',
        defaultMessage: '管理邮箱池状态与申领',
      })}
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
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (_keys, rows) => setSelectedRows(rows),
        }}
        tableAlertOptionRender={() => (
          <Space wrap>
            {BATCH_ACTIONS.map((a) => (
              <Button
                key={a.value}
                size="small"
                danger={a.value === 'retire' || a.value === 'force_release'}
                onClick={() => runBatch(a.value)}
              >
                {a.label}
              </Button>
            ))}
          </Space>
        )}
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
              options={POOL_STATUS_FILTER_OPTIONS}
              onChange={(v) => {
                setPoolStatus(v);
                actionRef.current?.reload();
              }}
            />,
            <Select
              key="provider"
              allowClear
              showSearch
              placeholder="来源"
              style={{ width: 160 }}
              value={provider}
              options={PROVIDER_FILTER_OPTIONS}
              onChange={(v) => {
                setProvider(v);
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
              provider,
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
