import { ReloadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useIntl } from '@umijs/max';
import { App, Button, Tag, Typography } from 'antd';
import React, { useRef } from 'react';
import { fetchAuditLogs, type AuditLogItem } from '@/services/outlook/audit';

const actionColor = (action?: string) => {
  const a = String(action || '').toLowerCase();
  if (
    a.includes('delete') ||
    a.includes('remove') ||
    a.includes('purge') ||
    a.includes('retire')
  ) {
    return 'error';
  }
  if (
    a.includes('create') ||
    a.includes('add') ||
    a.includes('import') ||
    a.includes('claim')
  ) {
    return 'success';
  }
  if (
    a.includes('update') ||
    a.includes('edit') ||
    a.includes('toggle') ||
    a.includes('move') ||
    a.includes('refresh')
  ) {
    return 'processing';
  }
  if (a.includes('export') || a.includes('login') || a.includes('logout')) {
    return 'warning';
  }
  return 'default';
};

const formatTime = (raw?: string | null) => {
  if (!raw) return '--';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw);
  return d.toLocaleString();
};

const formatDetails = (raw: unknown): string => {
  if (raw == null || raw === '') return '--';
  if (typeof raw === 'object') {
    try {
      return JSON.stringify(raw, null, 2);
    } catch {
      return String(raw);
    }
  }
  const text = String(raw);
  try {
    const parsed = JSON.parse(text);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
};

const AuditPage: React.FC = () => {
  const { message } = App.useApp();
  const intl = useIntl();
  const actionRef = useRef<ActionType>(null);

  const columns: ProColumns<AuditLogItem>[] = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      search: false,
      render: (_, row) => formatTime(row.created_at as string | undefined),
    },
    {
      title: '动作',
      dataIndex: 'action',
      width: 140,
      fieldProps: { placeholder: '如 create/delete' },
      render: (_, row) => (
        <Tag color={actionColor(row.action)}>{row.action || '--'}</Tag>
      ),
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
      dataIndex: 'details',
      search: false,
      width: 280,
      render: (_, row) => {
        const pretty = formatDetails(row.details ?? row.detail);
        if (pretty === '--') return '--';
        return (
          <Typography.Paragraph
            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
            style={{ marginBottom: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}
            copyable={{ text: pretty }}
          >
            {pretty}
          </Typography.Paragraph>
        );
      },
    },
    {
      title: 'IP',
      dataIndex: 'user_ip',
      width: 140,
      search: false,
      render: (_, row) => row.user_ip || row.ip || '--',
    },
    {
      title: 'Trace ID',
      dataIndex: 'trace_id',
      width: 160,
      ellipsis: true,
      search: false,
      render: (v) =>
        v ? (
          <Typography.Text copyable style={{ fontSize: 12 }}>
            {String(v)}
          </Typography.Text>
        ) : (
          '--'
        ),
    },
  ];

  return (
    <PageContainer
      title={intl.formatMessage({
        id: 'outlook.audit.title',
        defaultMessage: '审计日志',
      })}
      subTitle={intl.formatMessage({
        id: 'outlook.audit.subtitle',
        defaultMessage: '对接 /api/audit-logs · details / user_ip / trace_id',
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
