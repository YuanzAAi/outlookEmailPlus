import { ReloadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { App, Button, Segmented, Space, Tag } from 'antd';
import React, { useRef, useState } from 'react';
import {
  fetchFailedRefreshLogs,
  fetchRefreshLogs,
  type RefreshLogItem,
} from '@/services/outlook/refreshLogs';

const RefreshLogPage: React.FC = () => {
  const { message } = App.useApp();
  const actionRef = useRef<ActionType>(null);
  const [mode, setMode] = useState<'all' | 'failed'>('all');

  const columns: ProColumns<RefreshLogItem>[] = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      ellipsis: true,
      copyable: true,
      search: false,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      search: false,
      render: (_, row) => {
        const s = String(row.status || '').toLowerCase();
        const color =
          s.includes('success') || s === 'ok'
            ? 'success'
            : s.includes('fail') || s.includes('error')
              ? 'error'
              : 'default';
        return <Tag color={color}>{row.status || '--'}</Tag>;
      },
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
      search: false,
      render: (_, row) => row.message || row.error || '--',
    },
  ];

  return (
    <PageContainer
      title="刷新日志"
      subTitle="对接 /api/accounts/refresh-logs*"
      extra={
        <Space>
          <Segmented
            value={mode}
            options={[
              { label: '全部', value: 'all' },
              { label: '失败', value: 'failed' },
            ]}
            onChange={(v) => {
              setMode(v as 'all' | 'failed');
              actionRef.current?.reload();
            }}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => actionRef.current?.reload()}
          >
            刷新
          </Button>
        </Space>
      }
    >
      <ProTable<RefreshLogItem>
        rowKey={(row) =>
          String(row.id ?? `${row.created_at}-${row.email}-${row.status}`)
        }
        actionRef={actionRef}
        columns={columns}
        search={false}
        cardBordered
        options={false}
        request={async () => {
          try {
            const res =
              mode === 'failed'
                ? await fetchFailedRefreshLogs()
                : await fetchRefreshLogs({ limit: 200 });
            if (res?.success === false) {
              message.error('加载刷新日志失败');
              return { data: [], success: false };
            }
            return {
              data: res.logs || [],
              success: true,
            };
          } catch (error: any) {
            message.error(error?.message || '加载刷新日志失败');
            return { data: [], success: false };
          }
        }}
        pagination={{ pageSize: 50 }}
      />
    </PageContainer>
  );
};

export default RefreshLogPage;
