import { ReloadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { App, Button } from 'antd';
import React, { useRef } from 'react';
import { fetchAuditLogs, type AuditLogItem } from '@/services/outlook/audit';

const AuditPage: React.FC = () => {
  const { message } = App.useApp();
  const actionRef = useRef<ActionType>(null);

  const columns: ProColumns<AuditLogItem>[] = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '动作',
      dataIndex: 'action',
      width: 120,
      fieldProps: { placeholder: '如 create/delete' },
    },
    {
      title: '资源类型',
      dataIndex: 'resource_type',
      width: 140,
      fieldProps: { placeholder: '如 account/email' },
    },
    {
      title: '资源 ID',
      dataIndex: 'resource_id',
      ellipsis: true,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '详情',
      dataIndex: 'detail',
      ellipsis: true,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '操作者',
      dataIndex: 'operator',
      width: 120,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      width: 140,
      search: false,
      render: (v) => v || '--',
    },
  ];

  return (
    <PageContainer
      title="审计日志"
      subTitle="对接 /api/audit-logs"
      extra={
        <Button
          icon={<ReloadOutlined />}
          onClick={() => actionRef.current?.reload()}
        >
          刷新
        </Button>
      }
    >
      <ProTable<AuditLogItem>
        rowKey={(row) =>
          String(row.id ?? `${row.created_at}-${row.action}-${row.resource_id}`)
        }
        actionRef={actionRef}
        columns={columns}
        cardBordered
        options={{ density: true, reload: true, setting: true }}
        form={{ syncToUrl: false }}
        request={async (params) => {
          try {
            const pageSize = params.pageSize || 50;
            const current = params.current || 1;
            const res = await fetchAuditLogs({
              limit: pageSize,
              offset: (current - 1) * pageSize,
              action: (params.action as string) || undefined,
              resource_type: (params.resource_type as string) || undefined,
            });
            if (res?.success === false) {
              message.error(
                (typeof res.error === 'object' && res.error?.message) ||
                  '加载审计日志失败',
              );
              return { data: [], success: false, total: 0 };
            }
            return {
              data: res.logs || [],
              success: true,
              total: res.total ?? (res.logs || []).length,
            };
          } catch (error: any) {
            message.error(error?.message || '加载审计日志失败');
            return { data: [], success: false, total: 0 };
          }
        }}
        pagination={{ defaultPageSize: 50, showSizeChanger: true }}
      />
    </PageContainer>
  );
};

export default AuditPage;
