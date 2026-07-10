import {
  DeleteOutlined,
  MailOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { history, useLocation } from '@umijs/max';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Empty,
  List,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchAccounts, type AccountItem } from '@/services/outlook/accounts';
import {
  deleteEmails,
  fetchEmailDetail,
  fetchEmails,
  normalizeMethodParam,
  pickEmailsErrorMessage,
  type EmailDetail,
  type EmailFolder,
  type EmailListItem,
} from '@/services/outlook/emails';

const FOLDERS: Array<{ label: string; value: EmailFolder }> = [
  { label: '收件箱', value: 'inbox' },
  { label: '垃圾邮件', value: 'junkemail' },
  { label: '已删除', value: 'deleteditems' },
];

const PAGE_SIZE = 20;

function useAccountFromQuery(): string | undefined {
  const location = useLocation();
  return useMemo(() => {
    const params = new URLSearchParams(location.search || '');
    const account = params.get('account') || params.get('email') || '';
    return account.trim() || undefined;
  }, [location.search]);
}

function formatDate(value?: string) {
  if (!value) return '--';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
}

const MailboxPage: React.FC = () => {
  const { message } = App.useApp();
  const queryAccount = useAccountFromQuery();

  const [selectedEmail, setSelectedEmail] = useState<string | undefined>(
    queryAccount,
  );
  const [folder, setFolder] = useState<EmailFolder>('inbox');
  const [method, setMethod] = useState<string>('graph');
  const [skip, setSkip] = useState(0);
  const [emails, setEmails] = useState<EmailListItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [listErrorDetails, setListErrorDetails] = useState<any>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EmailDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const accountsQuery = useQuery({
    queryKey: ['mailbox-accounts'],
    queryFn: () =>
      fetchAccounts({ page: 1, page_size: 200, sort_by: 'email', sort_order: 'asc' }),
  });

  const accountOptions = useMemo(() => {
    const list = accountsQuery.data?.accounts || [];
    return list.map((a: AccountItem) => ({
      label: a.email,
      value: a.email,
    }));
  }, [accountsQuery.data]);

  useEffect(() => {
    if (queryAccount) {
      setSelectedEmail(queryAccount);
    }
  }, [queryAccount]);

  // 账号列表就绪后，若无选中则默认第一项
  useEffect(() => {
    if (selectedEmail) return;
    const first = accountsQuery.data?.accounts?.[0]?.email;
    if (first) setSelectedEmail(first);
  }, [accountsQuery.data, selectedEmail]);

  const loadEmails = useCallback(
    async (opts?: { append?: boolean; nextSkip?: number }) => {
      if (!selectedEmail) return;
      const append = !!opts?.append;
      const nextSkip = opts?.nextSkip ?? 0;
      setListLoading(true);
      setListError(null);
      setListErrorDetails(null);
      try {
        const res = await fetchEmails(selectedEmail, {
          method: normalizeMethodParam(method),
          folder,
          skip: nextSkip,
          top: PAGE_SIZE,
        });
        if (res?.success) {
          const list = res.emails || [];
          setEmails((prev) => (append ? [...prev, ...list] : list));
          setHasMore(!!res.has_more);
          setSkip(nextSkip);
          if (res.method) {
            setMethod(normalizeMethodParam(res.method));
          }
          if (!append) {
            setActiveId(null);
            setDetail(null);
            setSelectedIds([]);
          }
        } else {
          if (!append) {
            setEmails([]);
            setHasMore(false);
          }
          setListError(pickEmailsErrorMessage(res));
          setListErrorDetails(res?.details || res?.error?.details || null);
        }
      } catch (error: any) {
        const data = error?.response?.data || error?.data || error?.info;
        if (!append) {
          setEmails([]);
          setHasMore(false);
        }
        setListError(
          pickEmailsErrorMessage(data, error?.message || '获取邮件失败'),
        );
        setListErrorDetails(data?.details || data?.error?.details || null);
      } finally {
        setListLoading(false);
      }
    },
    [selectedEmail, folder, method],
  );

  // 切换账号/文件夹时重新加载（不跟 method 循环：method 由响应回写）
  useEffect(() => {
    if (!selectedEmail) return;
    void loadEmails({ append: false, nextSkip: 0 });
    // 仅账号/文件夹变化时拉取；method 由服务端回写，避免循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEmail, folder]);

  const openDetail = async (item: EmailListItem) => {
    if (!selectedEmail || !item?.id) return;
    setActiveId(item.id);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await fetchEmailDetail(selectedEmail, item.id, {
        method: normalizeMethodParam(method),
        folder,
      });
      if (res?.success && res.email) {
        setDetail(res.email);
      } else {
        message.error(pickEmailsErrorMessage(res, '获取邮件详情失败'));
      }
    } catch (error: any) {
      const data = error?.response?.data;
      message.error(
        pickEmailsErrorMessage(data, error?.message || '获取邮件详情失败'),
      );
    } finally {
      setDetailLoading(false);
    }
  };

  const onAccountChange = (email: string) => {
    setSelectedEmail(email);
    history.replace(`/mailbox?account=${encodeURIComponent(email)}`);
  };

  const onDeleteSelected = async () => {
    if (!selectedEmail || !selectedIds.length) return;
    try {
      const res = await deleteEmails(selectedEmail, selectedIds);
      if (res?.success === false) {
        message.error(pickEmailsErrorMessage(res, '删除失败'));
        return;
      }
      message.success(`已删除 ${selectedIds.length} 封`);
      setSelectedIds([]);
      setDetail(null);
      setActiveId(null);
      await loadEmails({ append: false, nextSkip: 0 });
    } catch (error: any) {
      const data = error?.response?.data;
      message.error(pickEmailsErrorMessage(data, error?.message || '删除失败'));
    }
  };

  const bodyHtml = useMemo(() => {
    if (!detail?.body) return '';
    if (String(detail.body_type || '').toLowerCase() === 'text') {
      const escaped = String(detail.body)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      return `<pre style="white-space:pre-wrap;font-family:inherit;margin:0">${escaped}</pre>`;
    }
    return detail.body;
  }, [detail]);

  return (
    <PageContainer
      title="邮箱"
      subTitle="对接 /api/emails/* · /api/email/*"
      extra={
        <Space wrap>
          <Select
            showSearch
            placeholder="选择账号"
            style={{ minWidth: 260 }}
            options={accountOptions}
            loading={accountsQuery.isLoading}
            value={selectedEmail}
            onChange={onAccountChange}
            optionFilterProp="label"
          />
          <Select
            style={{ width: 140 }}
            value={folder}
            options={FOLDERS}
            onChange={(v) => setFolder(v)}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={listLoading}
            onClick={() => void loadEmails({ append: false, nextSkip: 0 })}
            disabled={!selectedEmail}
          >
            刷新
          </Button>
          {selectedIds.length > 0 ? (
            <Popconfirm
              title={`确认永久删除选中的 ${selectedIds.length} 封邮件？`}
              onConfirm={() => void onDeleteSelected()}
            >
              <Button danger icon={<DeleteOutlined />}>
                删除选中
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      }
    >
      {listError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={listError}
          description={
            listErrorDetails ? (
              <Typography.Paragraph
                type="secondary"
                style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}
              >
                {typeof listErrorDetails === 'string'
                  ? listErrorDetails
                  : JSON.stringify(listErrorDetails, null, 2)}
              </Typography.Paragraph>
            ) : (
              '请检查账号 Token / 代理设置，或前往 Token 工具重新授权。'
            )
          }
          action={
            <Button
              size="small"
              onClick={() => void loadEmails({ append: false, nextSkip: 0 })}
            >
              重试
            </Button>
          }
        />
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(320px, 420px) 1fr',
          gap: 16,
          minHeight: 520,
        }}
      >
        <ProCard
          title={
            <Space>
              <MailOutlined />
              <span>邮件列表</span>
              {method ? <Tag>{method}</Tag> : null}
              <Typography.Text type="secondary">
                ({emails.length}
                {hasMore ? '+' : ''})
              </Typography.Text>
            </Space>
          }
          bordered
          bodyStyle={{ padding: 0, maxHeight: 640, overflow: 'auto' }}
        >
          {!selectedEmail ? (
            <Empty style={{ margin: 48 }} description="请先选择账号" />
          ) : (
            <Spin spinning={listLoading}>
              {emails.length === 0 && !listLoading ? (
                <Empty
                  style={{ margin: 48 }}
                  description={listError ? '加载失败' : '收件箱为空'}
                />
              ) : (
                <List
                  dataSource={emails}
                  rowKey={(item) => item.id}
                  renderItem={(item) => {
                    const active = item.id === activeId;
                    const unread = item.is_read === false;
                    return (
                      <List.Item
                        style={{
                          padding: '12px 16px',
                          cursor: 'pointer',
                          background: active ? 'rgba(184, 92, 56, 0.08)' : undefined,
                          borderLeft: active
                            ? '3px solid #B85C38'
                            : '3px solid transparent',
                        }}
                        onClick={() => void openDetail(item)}
                        actions={[
                          <Checkbox
                            key="cb"
                            checked={selectedIds.includes(item.id)}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              setSelectedIds((prev) =>
                                e.target.checked
                                  ? [...prev, item.id]
                                  : prev.filter((id) => id !== item.id),
                              );
                            }}
                          />,
                        ]}
                      >
                        <List.Item.Meta
                          title={
                            <Typography.Text strong={unread} ellipsis>
                              {item.subject || '无主题'}
                            </Typography.Text>
                          }
                          description={
                            <Space direction="vertical" size={0} style={{ width: '100%' }}>
                              <Typography.Text type="secondary" ellipsis>
                                {item.from || '未知发件人'}
                              </Typography.Text>
                              <Typography.Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                                {item.body_preview || ''}
                              </Typography.Text>
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                {formatDate(item.date)}
                              </Typography.Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    );
                  }}
                />
              )}
              {hasMore ? (
                <div style={{ padding: 12, textAlign: 'center' }}>
                  <Button
                    loading={listLoading}
                    onClick={() =>
                      void loadEmails({
                        append: true,
                        nextSkip: skip + PAGE_SIZE,
                      })
                    }
                  >
                    加载更多
                  </Button>
                </div>
              ) : null}
            </Spin>
          )}
        </ProCard>

        <ProCard
          title={detail?.subject || '邮件详情'}
          bordered
          bodyStyle={{ minHeight: 520 }}
        >
          <Spin spinning={detailLoading}>
            {!detail ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="选择一封邮件查看详情"
              />
            ) : (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div>
                  <Typography.Text type="secondary">发件人：</Typography.Text>
                  <Typography.Text>{detail.from || '--'}</Typography.Text>
                </div>
                {detail.to ? (
                  <div>
                    <Typography.Text type="secondary">收件人：</Typography.Text>
                    <Typography.Text>{detail.to}</Typography.Text>
                  </div>
                ) : null}
                {detail.cc ? (
                  <div>
                    <Typography.Text type="secondary">抄送：</Typography.Text>
                    <Typography.Text>{detail.cc}</Typography.Text>
                  </div>
                ) : null}
                <div>
                  <Typography.Text type="secondary">时间：</Typography.Text>
                  <Typography.Text>{formatDate(detail.date)}</Typography.Text>
                </div>
                <div
                  style={{
                    borderTop: '1px solid rgba(0,0,0,0.06)',
                    paddingTop: 12,
                  }}
                >
                  <iframe
                    title="email-body"
                    sandbox=""
                    srcDoc={bodyHtml}
                    style={{
                      width: '100%',
                      minHeight: 360,
                      border: 'none',
                      background: '#fff',
                    }}
                  />
                </div>
              </Space>
            )}
          </Spin>
        </ProCard>
      </div>
    </PageContainer>
  );
};

export default MailboxPage;
