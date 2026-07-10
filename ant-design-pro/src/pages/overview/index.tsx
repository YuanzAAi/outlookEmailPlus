import {
  PageContainer,
  ProCard,
  StatisticCard,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import React, { useMemo, useState } from 'react';
import {
  fetchOverviewActivity,
  fetchOverviewExternalApi,
  fetchOverviewPool,
  fetchOverviewSummary,
  fetchOverviewVerification,
  type OverviewActivity,
  type OverviewExternalApi,
  type OverviewPool,
  type OverviewSummary,
  type OverviewVerification,
} from '@/services/outlook/overview';
import {
  channelLabel,
  formatDurationMs,
  formatDurationSeconds,
  formatNumber,
  formatPercent,
  formatTime,
} from './utils';

type TabKey =
  | 'summary'
  | 'verification'
  | 'external-api'
  | 'pool'
  | 'activity';

function ProgressList({
  items,
}: {
  items: Array<{
    label: string;
    value: number;
    total: number;
    suffix?: string;
    status?: 'success' | 'exception' | 'normal' | 'active';
  }>;
}) {
  if (!items.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {items.map((item) => {
        const percent =
          item.total > 0
            ? Math.min(100, Math.round((item.value / item.total) * 100))
            : 0;
        return (
          <div key={item.label}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: 4,
              }}
            >
              <Typography.Text>{item.label}</Typography.Text>
              <Typography.Text type="secondary">
                {item.suffix ||
                  `${formatNumber(item.value)} / ${formatNumber(item.total)}`}
              </Typography.Text>
            </div>
            <Progress
              percent={percent}
              size="small"
              status={item.status || 'active'}
              showInfo={false}
            />
          </div>
        );
      })}
    </Space>
  );
}

const SummaryPane: React.FC<{ data?: OverviewSummary; loading: boolean }> = ({
  data,
  loading,
}) => {
  const account = data?.account_status || {};
  const pool = data?.pool_snapshot || {};
  const refresh = data?.refresh_health || {};
  const kpi = data?.kpi || {};

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '总账号数',
              value: account.total || 0,
              description: `活跃 ${formatNumber(account.active || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '邮箱池可用',
              value: pool.available || 0,
              description: `占用 ${formatNumber(pool.in_use || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '今日验证码提取',
              value: kpi.verification_extracted || 0,
              description: `临时邮箱 ${formatNumber(kpi.temp_emails_active || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '最近刷新成功率',
              value: formatPercent(refresh.success_rate_7d || 0),
              description: `失败 ${formatNumber(refresh.last_fail_count || 0)}`,
            }}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <ProCard title="账号状态分布" bordered loading={loading}>
            <ProgressList
              items={[
                {
                  label: '活跃',
                  value: account.active || 0,
                  total: account.total || 0,
                  status: 'success',
                },
                {
                  label: '过期',
                  value: account.expired || 0,
                  total: account.total || 0,
                  status: 'exception',
                },
                {
                  label: '待刷新',
                  value: account.pending_refresh || 0,
                  total: account.total || 0,
                },
                {
                  label: '异常',
                  value: account.error || 0,
                  total: account.total || 0,
                  status: 'exception',
                },
              ]}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="邮箱池快照" bordered loading={loading}>
            <ProgressList
              items={[
                {
                  label: '可用',
                  value: pool.available || 0,
                  total: pool.total || 0,
                  status: 'success',
                },
                {
                  label: '占用中',
                  value: pool.in_use || 0,
                  total: pool.total || 0,
                },
                {
                  label: '冷却中',
                  value: pool.cooldown || 0,
                  total: pool.total || 0,
                },
                {
                  label: '已使用',
                  value: pool.used || 0,
                  total: pool.total || 0,
                },
              ]}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="刷新健康" bordered loading={loading}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div className="ov-kv">
                最近启动：<strong>{formatTime(refresh.last_run_at)}</strong>
              </div>
              <div>
                最近成功数：
                <strong>{formatNumber(refresh.last_success_count || 0)}</strong>
              </div>
              <div>
                最近失败数：
                <strong>{formatNumber(refresh.last_fail_count || 0)}</strong>
              </div>
              <div>
                最近耗时：
                <strong>
                  {formatDurationSeconds(refresh.last_duration_s || 0)}
                </strong>
              </div>
            </Space>
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="今日快捷数字" bordered loading={loading}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                今日收件：
                <strong>{formatNumber(kpi.emails_received || 0)}</strong>
              </div>
              <div>
                验证码提取：
                <strong>
                  {formatNumber(kpi.verification_extracted || 0)}
                </strong>
              </div>
              <div>
                活跃临时邮箱：
                <strong>{formatNumber(kpi.temp_emails_active || 0)}</strong>
              </div>
            </Space>
          </ProCard>
        </Col>
      </Row>
    </Space>
  );
};

const VerificationPane: React.FC<{
  data?: OverviewVerification;
  loading: boolean;
}> = ({ data, loading }) => {
  const kpi = data?.kpi || {};
  const channels = data?.channel_stats || [];
  const recent = data?.recent || [];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '近 7 天提取次数',
              value: kpi.total_count || 0,
              description: `成功 ${formatNumber(kpi.success_count || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '总体成功率',
              value: formatPercent(kpi.success_rate || 0),
              description: `失败 ${formatNumber(kpi.fail_count || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: 'AI 兜底次数',
              value: kpi.ai_used_count || 0,
              description: `AI 成功率 ${formatPercent(kpi.ai_success_rate || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '平均耗时',
              value: formatDurationMs(kpi.avg_duration_ms || 0),
              description: `P95 ${formatDurationMs(kpi.p95_duration_ms || 0)}`,
            }}
          />
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <ProCard title="各通道成功率" bordered loading={loading}>
            <ProgressList
              items={channels.map((item) => ({
                label: channelLabel(item.channel, item.label),
                value: item.success_count || 0,
                total: item.count || 0,
                suffix: `${formatPercent(item.success_rate || 0)} · ${formatNumber(item.count || 0)} 次`,
              }))}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="各通道平均耗时" bordered loading={loading}>
            <ProgressList
              items={channels.map((item) => {
                const max = Math.max(
                  ...channels.map((row) => Number(row.avg_duration_ms || 0)),
                  1,
                );
                return {
                  label: channelLabel(item.channel, item.label),
                  value: item.avg_duration_ms || 0,
                  total: max,
                  suffix: formatDurationMs(item.avg_duration_ms || 0),
                };
              })}
            />
          </ProCard>
        </Col>
      </Row>
      <ProCard title="最近提取记录" bordered loading={loading}>
        <Table
          size="small"
          rowKey={(_, index) => String(index)}
          pagination={false}
          dataSource={recent}
          locale={{ emptyText: '暂无记录' }}
          columns={[
            {
              title: '时间',
              dataIndex: 'started_at',
              render: (v) => formatTime(v),
            },
            {
              title: '账号',
              dataIndex: 'account_email',
              render: (v) => v || '--',
            },
            {
              title: '通道',
              render: (_, row) =>
                channelLabel(row.channel, row.channel_label),
            },
            {
              title: '结果',
              dataIndex: 'code_found',
              render: (v) => v || '--',
            },
            {
              title: '耗时',
              dataIndex: 'duration_ms',
              render: (v) => formatDurationMs(v),
            },
            {
              title: '状态',
              dataIndex: 'result_type',
              render: (v, row) => (
                <Tag color={v && v !== 'none' ? 'success' : 'error'}>
                  {v || row.error_code || 'none'}
                </Tag>
              ),
            },
          ]}
        />
      </ProCard>
    </Space>
  );
};

const ExternalApiPane: React.FC<{
  data?: OverviewExternalApi;
  loading: boolean;
}> = ({ data, loading }) => {
  const kpi = data?.kpi || {};
  const byEndpoint = data?.by_endpoint || [];
  const callerRank = data?.caller_rank || [];
  const daily = data?.daily_series || [];
  const maxDaily = Math.max(...daily.map((d) => Number(d.count || 0)), 1);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '今日调用量',
              value: kpi.today_calls || 0,
              description: `7 日 ${formatNumber(kpi.week_calls || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '调用波动',
              value: formatPercent(kpi.today_vs_yesterday_rate || 0),
              description: '对比昨日',
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '7 日成功率',
              value: formatPercent(kpi.success_rate || 0),
              description: `错误 ${formatNumber(kpi.error_count || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '活跃调用方',
              value: kpi.active_callers || 0,
              description: '近 7 日有调用',
            }}
          />
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <ProCard title="7 日调用趋势" bordered loading={loading}>
            {daily.length ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                {daily.map((item) => (
                  <div key={String(item.date)}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                      }}
                    >
                      <span>{item.date || '--'}</span>
                      <span>{formatNumber(item.count || 0)}</span>
                    </div>
                    <Progress
                      percent={Math.round(
                        ((item.count || 0) / maxDaily) * 100,
                      )}
                      showInfo={false}
                      size="small"
                    />
                  </div>
                ))}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="接口占比" bordered loading={loading}>
            <ProgressList
              items={byEndpoint.map((item) => ({
                label: item.endpoint || '--',
                value: item.count || 0,
                total: kpi.week_calls || 0,
                suffix: `${formatNumber(item.count || 0)} · ${formatPercent(item.rate || 0)}`,
              }))}
            />
          </ProCard>
        </Col>
      </Row>
      <ProCard title="调用方排名" bordered loading={loading}>
        <Table
          size="small"
          rowKey={(_, i) => String(i)}
          pagination={false}
          dataSource={callerRank}
          locale={{ emptyText: '暂无调用方' }}
          columns={[
            {
              title: '调用方',
              render: (_, row) => row.key_name || row.caller_id || '--',
            },
            {
              title: '今日',
              dataIndex: 'today_calls',
              render: (v) => formatNumber(v || 0),
            },
            {
              title: '7 日',
              dataIndex: 'week_calls',
              render: (v) => formatNumber(v || 0),
            },
            {
              title: '成功率',
              dataIndex: 'success_rate',
              render: (v) => formatPercent(v || 0),
            },
            {
              title: '最近调用',
              dataIndex: 'last_used_at',
              render: (v) => v || '--',
            },
          ]}
        />
      </ProCard>
    </Space>
  );
};

const PoolPane: React.FC<{ data?: OverviewPool; loading: boolean }> = ({
  data,
  loading,
}) => {
  const kpi = data?.kpi || {};
  const dist = data?.operation_distribution || {};
  const distTotal = Object.values(dist).reduce(
    (sum, n) => sum + Number(n || 0),
    0,
  );
  const topProjects = data?.project_top5 || [];
  const recent = data?.recent_operations || [];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '可用账号',
              value: kpi.available || 0,
              description: `占用 ${formatNumber(kpi.in_use || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '冷却中',
              value: kpi.cooldown || 0,
              description: `已使用 ${formatNumber(kpi.used || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '近 7 天领取',
              value: kpi.claim_count_7d || 0,
              description: `完成率 ${formatPercent(kpi.complete_success_rate || 0)}`,
            }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '最长占用',
              value: formatDurationSeconds(kpi.max_claimed_duration_s || 0),
              description: '当前占用中',
            }}
          />
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <ProCard title="操作分布" bordered loading={loading}>
            <ProgressList
              items={[
                {
                  label: '领取',
                  value: dist.claim || 0,
                  total: distTotal,
                },
                {
                  label: '完成',
                  value: dist.complete || 0,
                  total: distTotal,
                  status: 'success',
                },
                {
                  label: '释放',
                  value: dist.release || 0,
                  total: distTotal,
                },
                {
                  label: '过期回收',
                  value: dist.expire || 0,
                  total: distTotal,
                  status: 'exception',
                },
              ]}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={12}>
          <ProCard title="项目 Top 5" bordered loading={loading}>
            <Table
              size="small"
              pagination={false}
              rowKey={(_, i) => String(i)}
              dataSource={topProjects}
              locale={{ emptyText: '暂无项目' }}
              columns={[
                {
                  title: '项目',
                  dataIndex: 'project_key',
                  render: (v) => v || '--',
                },
                {
                  title: '账号数',
                  dataIndex: 'account_count',
                  render: (v) => formatNumber(v || 0),
                },
                {
                  title: '成功数',
                  dataIndex: 'success_count',
                  render: (v) => formatNumber(v || 0),
                },
                {
                  title: '复用率',
                  dataIndex: 'reuse_rate',
                  render: (v) => formatPercent(v || 0),
                },
              ]}
            />
          </ProCard>
        </Col>
      </Row>
      <ProCard title="最近邮箱池操作" bordered loading={loading}>
        <Table
          size="small"
          pagination={false}
          rowKey={(_, i) => String(i)}
          dataSource={recent}
          locale={{ emptyText: '暂无操作' }}
          columns={Object.keys(recent[0] || { action: 1, created_at: 1 }).map(
            (key) => ({
              title: key,
              dataIndex: key,
              render: (v: any) =>
                typeof v === 'object' ? JSON.stringify(v) : String(v ?? '--'),
            }),
          )}
        />
      </ProCard>
    </Space>
  );
};

const ActivityPane: React.FC<{
  data?: OverviewActivity;
  loading: boolean;
}> = ({ data, loading }) => {
  const recent = (data?.recent || data?.items || []) as Array<
    Record<string, any>
  >;
  const kpiEntries = Object.entries(data?.kpi || {});

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {kpiEntries.length ? (
        <Row gutter={[16, 16]}>
          {kpiEntries.slice(0, 4).map(([key, value]) => (
            <Col xs={24} sm={12} md={6} key={key}>
              <StatisticCard
                loading={loading}
                statistic={{
                  title: key,
                  value:
                    typeof value === 'number'
                      ? value
                      : String(value ?? '--'),
                }}
              />
            </Col>
          ))}
        </Row>
      ) : null}
      <ProCard title="系统活动" bordered loading={loading}>
        {recent.length ? (
          <Table
            size="small"
            pagination={false}
            rowKey={(_, i) => String(i)}
            dataSource={recent}
            columns={Object.keys(recent[0] || {}).map((key) => ({
              title: key,
              dataIndex: key,
              render: (v: any) =>
                typeof v === 'object' ? JSON.stringify(v) : String(v ?? '--'),
            }))}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={loading ? '加载中…' : '暂无活动数据'}
          />
        )}
      </ProCard>
    </Space>
  );
};

const OverviewPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('summary');

  const summaryQuery = useQuery({
    queryKey: ['overview', 'summary'],
    queryFn: fetchOverviewSummary,
    enabled: activeTab === 'summary',
  });
  const verificationQuery = useQuery({
    queryKey: ['overview', 'verification'],
    queryFn: fetchOverviewVerification,
    enabled: activeTab === 'verification',
  });
  const externalQuery = useQuery({
    queryKey: ['overview', 'external-api'],
    queryFn: fetchOverviewExternalApi,
    enabled: activeTab === 'external-api',
  });
  const poolQuery = useQuery({
    queryKey: ['overview', 'pool'],
    queryFn: fetchOverviewPool,
    enabled: activeTab === 'pool',
  });
  const activityQuery = useQuery({
    queryKey: ['overview', 'activity'],
    queryFn: fetchOverviewActivity,
    enabled: activeTab === 'activity',
  });

  const activeMeta = useMemo(() => {
    const map: Record<
      TabKey,
      {
        error: unknown;
        isFetching: boolean;
        dataUpdatedAt: number;
        refetch: () => void;
      }
    > = {
      summary: {
        error: summaryQuery.error,
        isFetching: summaryQuery.isFetching,
        dataUpdatedAt: summaryQuery.dataUpdatedAt,
        refetch: () => {
          void summaryQuery.refetch();
        },
      },
      verification: {
        error: verificationQuery.error,
        isFetching: verificationQuery.isFetching,
        dataUpdatedAt: verificationQuery.dataUpdatedAt,
        refetch: () => {
          void verificationQuery.refetch();
        },
      },
      'external-api': {
        error: externalQuery.error,
        isFetching: externalQuery.isFetching,
        dataUpdatedAt: externalQuery.dataUpdatedAt,
        refetch: () => {
          void externalQuery.refetch();
        },
      },
      pool: {
        error: poolQuery.error,
        isFetching: poolQuery.isFetching,
        dataUpdatedAt: poolQuery.dataUpdatedAt,
        refetch: () => {
          void poolQuery.refetch();
        },
      },
      activity: {
        error: activityQuery.error,
        isFetching: activityQuery.isFetching,
        dataUpdatedAt: activityQuery.dataUpdatedAt,
        refetch: () => {
          void activityQuery.refetch();
        },
      },
    };
    return map[activeTab];
  }, [
    activeTab,
    summaryQuery.error,
    summaryQuery.isFetching,
    summaryQuery.dataUpdatedAt,
    summaryQuery.refetch,
    verificationQuery.error,
    verificationQuery.isFetching,
    verificationQuery.dataUpdatedAt,
    verificationQuery.refetch,
    externalQuery.error,
    externalQuery.isFetching,
    externalQuery.dataUpdatedAt,
    externalQuery.refetch,
    poolQuery.error,
    poolQuery.isFetching,
    poolQuery.dataUpdatedAt,
    poolQuery.refetch,
    activityQuery.error,
    activityQuery.isFetching,
    activityQuery.dataUpdatedAt,
    activityQuery.refetch,
  ]);

  const lastRefresh =
    activeMeta.dataUpdatedAt > 0
      ? new Date(activeMeta.dataUpdatedAt).toLocaleString('zh-CN')
      : '--';

  const activeError = activeMeta.error as any;

  return (
    <PageContainer
      title="数据概览"
      subTitle="账号、验证码、对外 API、邮箱池与系统活动"
      extra={
        <Space>
          <Typography.Text type="secondary">
            最近刷新：{lastRefresh}
          </Typography.Text>
          <Button loading={activeMeta.isFetching} onClick={activeMeta.refetch}>
            刷新
          </Button>
        </Space>
      }
    >
      {activeError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="概览数据加载失败"
          description={
            activeError?.message ||
            activeError?.info?.errorMessage ||
            '请确认已登录且后端可用'
          }
        />
      ) : null}

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as TabKey)}
        items={[
          {
            key: 'summary',
            label: '总览',
            children: (
              <SummaryPane
                data={summaryQuery.data}
                loading={summaryQuery.isLoading}
              />
            ),
          },
          {
            key: 'verification',
            label: '验证码提取',
            children: (
              <VerificationPane
                data={verificationQuery.data}
                loading={verificationQuery.isLoading}
              />
            ),
          },
          {
            key: 'external-api',
            label: '对外 API',
            children: (
              <ExternalApiPane
                data={externalQuery.data}
                loading={externalQuery.isLoading}
              />
            ),
          },
          {
            key: 'pool',
            label: '邮箱池',
            children: (
              <PoolPane data={poolQuery.data} loading={poolQuery.isLoading} />
            ),
          },
          {
            key: 'activity',
            label: '系统活动',
            children: (
              <ActivityPane
                data={activityQuery.data}
                loading={activityQuery.isLoading}
              />
            ),
          },
        ]}
      />
    </PageContainer>
  );
};

export default OverviewPage;
