import {
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  MailOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import {
  ModalForm,
  PageContainer,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { useIntl } from '@umijs/max';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import React, { useMemo, useRef, useState } from 'react';
import {
  batchDeleteAccounts,
  batchNotificationToggle,
  batchUpdateAccountGroup,
  batchUpdateAccountStatus,
  createAccount,
  deleteAccount,
  downloadBlob,
  exportSelectedGroups,
  fetchAccount,
  fetchAccounts,
  fetchProviders,
  pickAccountErrorMessage,
  refreshSelectedAccounts,
  toggleAccountTelegram,
  updateAccount,
  verifyExportPassword,
  type AccountItem,
  type RefreshSelectedEvent,
} from '@/services/outlook/accounts';
import {
  fetchGroups,
  isTempMailboxGroup,
  type GroupItem,
} from '@/services/outlook/groups';
import {
  ACCOUNT_STATUS_OPTIONS,
  accountStatusLabel,
  refreshStatusLabel,
} from '@/utils/statusLabels';

const statusColor = (status?: string) => {
  const s = String(status || '').toLowerCase();
  if (s === 'active') return 'success';
  if (s === 'expired' || s === 'inactive' || s === 'disabled') return 'default';
  if (s === 'error' || s === 'failed') return 'error';
  return 'processing';
};

const AccountsPage: React.FC = () => {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const actionRef = useRef<ActionType>(null);
  const [groupId, setGroupId] = useState<number | undefined>(undefined);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<AccountItem | null>(null);
  const [editAccountType, setEditAccountType] = useState<string>('outlook');
  const [editLoading, setEditLoading] = useState(false);
  const [editForm] = Form.useForm();
  const [importProvider, setImportProvider] = useState<string>('outlook');
  const [selectedRows, setSelectedRows] = useState<AccountItem[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportGroupIds, setExportGroupIds] = useState<number[]>([]);
  const [exportPassword, setExportPassword] = useState('');
  const [exporting, setExporting] = useState(false);

  const groupsQuery = useQuery({
    queryKey: ['groups'],
    queryFn: fetchGroups,
  });
  const providersQuery = useQuery({
    queryKey: ['providers'],
    queryFn: fetchProviders,
  });

  const normalGroups = useMemo(() => {
    return (groupsQuery.data?.groups || []).filter(
      (g: GroupItem) => !isTempMailboxGroup(g),
    );
  }, [groupsQuery.data]);

  const groupOptions = useMemo(
    () =>
      normalGroups.map((g) => ({
        label: `${g.name} (${g.account_count || 0})`,
        value: g.id,
      })),
    [normalGroups],
  );

  const providerOptions = useMemo(() => {
    const list = providersQuery.data?.providers || [];
    if (!list.length) {
      return [
        { label: 'Outlook', value: 'outlook' },
        { label: '智能识别（混合导入）', value: 'auto' },
        { label: '自定义 IMAP', value: 'custom' },
      ];
    }
    return list.map((p) => ({
      label: p.label || p.key,
      value: p.key,
    }));
  }, [providersQuery.data]);

  const openEdit = async (row: AccountItem) => {
    setEditing(row);
    setEditAccountType(row.account_type || 'outlook');
    setEditLoading(true);
    try {
      const res = await fetchAccount(row.id);
      if (res?.success === false || !res.account) {
        message.error(pickAccountErrorMessage(res, '加载账号失败'));
        setEditing(null);
        return;
      }
      const acc = res.account;
      setEditAccountType(acc.account_type || 'outlook');
      editForm.setFieldsValue({
        email: acc.email,
        password: '',
        client_id: acc.client_id || '',
        refresh_token: '',
        group_id: acc.group_id || undefined,
        remark: acc.remark || '',
        status: acc.status || 'active',
        account_type: acc.account_type || 'outlook',
      });
    } catch (error: any) {
      message.error(error?.message || '加载账号失败');
      setEditing(null);
    } finally {
      setEditLoading(false);
    }
  };

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
        <Tag
          color={statusColor(row.status)}
          style={{ cursor: 'pointer' }}
          onClick={() => void onToggleStatus(row)}
        >
          {accountStatusLabel(row.status)}
        </Tag>
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
      title: '通知',
      dataIndex: 'telegram_push_enabled',
      width: 90,
      search: false,
      render: (_, row) => (
        <Switch
          size="small"
          checked={!!(row.telegram_push_enabled ?? row.notification_enabled)}
          onChange={(checked) => void onToggleTelegram(row, checked)}
        />
      ),
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
          <Typography.Text>{row.last_refresh_at || '--'}</Typography.Text>
          {row.last_refresh_status ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {refreshStatusLabel(row.last_refresh_status)}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 240,
      render: (_, row) => [
        <Button
          key="mailbox"
          type="link"
          icon={<MailOutlined />}
          href={`/mailbox?account=${encodeURIComponent(row.email)}`}
        >
          邮件
        </Button>,
        <Button
          key="edit"
          type="link"
          icon={<EditOutlined />}
          onClick={() => void openEdit(row)}
        >
          编辑
        </Button>,
        <Popconfirm
          key="delete"
          title="确认删除该账号？"
          onConfirm={async () => {
            try {
              const res = await deleteAccount(row.id);
              if (res?.success === false) {
                message.error(
                  pickAccountErrorMessage(res, res.message || '删除失败'),
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

  const selectedIds = selectedRows.map((r) => r.id);

  const onToggleStatus = async (row: AccountItem) => {
    const next =
      String(row.status || '').toLowerCase() === 'active' ? 'inactive' : 'active';
    try {
      const res = await batchUpdateAccountStatus([row.id], next);
      if (res?.success === false) {
        message.error(pickAccountErrorMessage(res, '状态更新失败'));
        return;
      }
      message.success(res.message || `已设为${accountStatusLabel(next)}`);
      actionRef.current?.reload();
    } catch (error: any) {
      message.error(error?.message || '状态更新失败');
    }
  };

  const onToggleTelegram = async (row: AccountItem, enabled: boolean) => {
    try {
      const res = await toggleAccountTelegram(row.id, enabled);
      if (res?.success === false) {
        message.error(pickAccountErrorMessage(res, '通知切换失败'));
        return;
      }
      message.success(res.message || (enabled ? '已开启通知' : '已关闭通知'));
      actionRef.current?.reload();
    } catch (error: any) {
      message.error(error?.message || '通知切换失败');
    }
  };

  const runBatch = async (
    title: string,
    runner: () => Promise<void>,
  ) => {
    if (!selectedIds.length) {
      message.warning('请先勾选账号');
      return;
    }
    modal.confirm({
      title,
      onOk: async () => {
        try {
          await runner();
          setSelectedRows([]);
          actionRef.current?.reload();
        } catch (error: any) {
          message.error(error?.message || '批量操作失败');
        }
      },
    });
  };

  const onExport = async () => {
    if (!exportGroupIds.length) {
      message.warning('请选择要导出的分组');
      return;
    }
    if (!exportPassword) {
      message.warning('请输入登录密码以二次验证');
      return;
    }
    setExporting(true);
    try {
      const verify = await verifyExportPassword(exportPassword);
      if (verify?.success === false || !verify.verify_token) {
        message.error(pickAccountErrorMessage(verify, '密码验证失败'));
        return;
      }
      const { blob, filename } = await exportSelectedGroups(
        exportGroupIds,
        verify.verify_token,
      );
      downloadBlob(blob, filename);
      message.success('导出成功');
      setExportOpen(false);
      setExportPassword('');
    } catch (error: any) {
      message.error(error?.message || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const isImapEdit = String(editAccountType || '').toLowerCase() === 'imap';

  return (
    <PageContainer
      title={intl.formatMessage({
        id: 'outlook.accounts.title',
        defaultMessage: '账号管理',
      })}
      subTitle={intl.formatMessage({
        id: 'outlook.accounts.subtitle',
        defaultMessage: '管理已接入的邮箱账号',
      })}
      extra={
        <Space wrap>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => actionRef.current?.reload()}
          >
            刷新
          </Button>
          <Button
            icon={<ExportOutlined />}
            onClick={() => {
              setExportGroupIds(groupOptions.map((g) => g.value));
              setExportOpen(true);
            }}
          >
            导出
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setImportProvider('outlook');
              setImportOpen(true);
            }}
          >
            添加账号
          </Button>
        </Space>
      }
    >
      <ProTable<AccountItem>
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
            <Button
              size="small"
              onClick={() =>
                void runBatch('批量设为正常？', async () => {
                  const res = await batchUpdateAccountStatus(
                    selectedIds,
                    'active',
                  );
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量状态失败'),
                    );
                  }
                  message.success(res.message || '已批量激活');
                })
              }
            >
              批量启用
            </Button>
            <Button
              size="small"
              onClick={() =>
                void runBatch('批量设为停用？', async () => {
                  const res = await batchUpdateAccountStatus(
                    selectedIds,
                    'inactive',
                  );
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量状态失败'),
                    );
                  }
                  message.success(res.message || '已批量停用');
                })
              }
            >
              批量停用
            </Button>
            <Button
              size="small"
              onClick={() =>
                void runBatch('批量开启通知？', async () => {
                  const res = await batchNotificationToggle(selectedIds, true);
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量通知失败'),
                    );
                  }
                  message.success(res.message || '已开启通知');
                })
              }
            >
              开通知
            </Button>
            <Button
              size="small"
              onClick={() =>
                void runBatch('批量关闭通知？', async () => {
                  const res = await batchNotificationToggle(selectedIds, false);
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量通知失败'),
                    );
                  }
                  message.success(res.message || '已关闭通知');
                })
              }
            >
              关通知
            </Button>
            <Button
              size="small"
              icon={<SyncOutlined />}
              onClick={() =>
                void runBatch('刷新选中账号 Token？', async () => {
                  const loadingKey = 'refresh-selected-token';
                  message.loading({
                    content: '正在刷新 Token…',
                    key: loadingKey,
                    duration: 0,
                  });
                  try {
                    const res = await refreshSelectedAccounts(selectedIds, {
                      onEvent: (event: RefreshSelectedEvent) => {
                        if (event.type === 'start') {
                          message.loading({
                            content: `正在刷新 Token… 0 / ${event.total}`,
                            key: loadingKey,
                            duration: 0,
                          });
                        } else if (event.type === 'progress') {
                          const done =
                            event.result === 'processing'
                              ? Math.max(0, (event.current || 1) - 1)
                              : event.current;
                          message.loading({
                            content: `正在刷新 Token… ${done} / ${event.total}`,
                            key: loadingKey,
                            duration: 0,
                          });
                        } else if (event.type === 'delay') {
                          message.loading({
                            content: `限流等待约 ${Math.ceil(event.seconds)} 秒…`,
                            key: loadingKey,
                            duration: 0,
                          });
                        }
                      },
                    });
                    if (res.failed_count > 0) {
                      const detail =
                        res.failed_list
                          ?.slice(0, 5)
                          .map(
                            (f) =>
                              `${f.email || f.id || '?'}: ${f.error || '失败'}`,
                          )
                          .join('；') || '';
                      message.warning({
                        content: detail
                          ? `${res.message}（${detail}${
                              res.failed_list.length > 5 ? '…' : ''
                            }）`
                          : res.message,
                        key: loadingKey,
                      });
                    } else {
                      message.success({
                        content: res.message || 'Token 刷新完成',
                        key: loadingKey,
                      });
                    }
                  } catch (error) {
                    message.destroy(loadingKey);
                    throw error;
                  }
                })
              }
            >
              刷新 Token
            </Button>
            <Select
              size="small"
              placeholder="移到分组"
              style={{ width: 160 }}
              options={groupOptions}
              onChange={(gid) =>
                void runBatch(`批量移动到分组 #${gid}？`, async () => {
                  const res = await batchUpdateAccountGroup(selectedIds, gid);
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量移组失败'),
                    );
                  }
                  message.success(res.message || '已移组');
                })
              }
            />
            <Button
              size="small"
              danger
              onClick={() =>
                void runBatch(`确认删除选中的 ${selectedIds.length} 个账号？`, async () => {
                  const res = await batchDeleteAccounts(selectedIds);
                  if (res?.success === false) {
                    throw new Error(
                      pickAccountErrorMessage(res, '批量删除失败'),
                    );
                  }
                  message.success(res.message || '已删除');
                })
              }
            >
              批量删除
            </Button>
          </Space>
        )}
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
              sort_by: 'refresh_time',
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

      <ModalForm
        title="添加 / 导入账号"
        open={importOpen}
        modalProps={{
          destroyOnHidden: true,
          onCancel: () => setImportOpen(false),
        }}
        onOpenChange={setImportOpen}
        initialValues={{
          provider: 'outlook',
          group_id: groupId,
          add_to_pool: false,
          duplicate_strategy: 'skip',
          imap_port: 993,
        }}
        onValuesChange={(changed) => {
          if (Object.prototype.hasOwnProperty.call(changed, 'provider')) {
            setImportProvider(String(changed.provider || 'outlook'));
          }
        }}
        onFinish={async (values) => {
          try {
            const provider = String(values.provider || 'outlook').toLowerCase();
            const payload: Record<string, any> = {
              account_string: String(values.account_string || '').trim(),
              add_to_pool: !!values.add_to_pool,
            };
            if (!payload.account_string) {
              message.error('请输入账号信息');
              return false;
            }
            if (provider === 'auto') {
              payload.provider = 'auto';
              payload.group_id = null;
              payload.duplicate_strategy = values.duplicate_strategy || 'skip';
              if (values.imap_host) {
                payload.imap_host = values.imap_host;
                payload.imap_port = values.imap_port || 993;
              }
            } else {
              payload.provider = provider;
              payload.group_id = values.group_id;
              if (provider === 'custom') {
                if (values.imap_host) {
                  payload.imap_host = values.imap_host;
                  payload.imap_port = values.imap_port || 993;
                }
              } else if (provider !== 'outlook' && values.imap_host) {
                payload.imap_host = values.imap_host;
                payload.imap_port = values.imap_port || 993;
              }
            }

            const res = await createAccount(payload);
            if (res?.success === false) {
              message.error(pickAccountErrorMessage(res, '导入失败'));
              return false;
            }
            let msg = res.message || '导入成功';
            const summary = res.summary;
            if (summary?.mode === 'auto' && summary.by_provider) {
              const parts = Object.entries(summary.by_provider as Record<string, any>)
                .map(([prov, stats]) => {
                  const s = stats || {};
                  return `${prov}: 成功 ${s.imported || 0}${
                    s.skipped ? `, 跳过 ${s.skipped}` : ''
                  }${s.failed ? `, 失败 ${s.failed}` : ''}`;
                })
                .join('；');
              if (parts) msg = `${msg}（${parts}）`;
            }
            message.success(msg);
            actionRef.current?.reload();
            return true;
          } catch (error: any) {
            message.error(
              pickAccountErrorMessage(
                error?.response?.data,
                error?.message || '导入失败',
              ),
            );
            return false;
          }
        }}
      >
        <ProFormSelect
          name="provider"
          label="提供商"
          options={providerOptions}
          rules={[{ required: true, message: '请选择提供商' }]}
          fieldProps={{ loading: providersQuery.isLoading }}
        />
        {importProvider !== 'auto' ? (
          <ProFormSelect
            name="group_id"
            label="目标分组"
            options={groupOptions}
            rules={[{ required: true, message: '请选择分组' }]}
            fieldProps={{ loading: groupsQuery.isLoading }}
          />
        ) : (
          <ProFormSelect
            name="duplicate_strategy"
            label="重复账号策略"
            options={[
              { label: '跳过', value: 'skip' },
              { label: '覆盖', value: 'overwrite' },
            ]}
          />
        )}
        <ProFormTextArea
          name="account_string"
          label="账号文本"
          placeholder={
            importProvider === 'outlook'
              ? '每行一个：邮箱----密码----client_id----refresh_token'
              : importProvider === 'auto'
                ? '支持混合格式，每行一个账号…\nOutlook: 邮箱----密码----client_id----refresh_token\nIMAP: 邮箱----授权码----provider\n临时邮箱: 仅邮箱地址'
                : '每行一个：邮箱----IMAP授权码/应用密码'
          }
          rules={[{ required: true, message: '请输入账号信息' }]}
          fieldProps={{ rows: 8 }}
        />
        {(importProvider === 'custom' ||
          importProvider === 'auto' ||
          (importProvider !== 'outlook' && importProvider !== 'auto')) && (
          <>
            <ProFormText
              name="imap_host"
              label={
                importProvider === 'auto'
                  ? '备用 IMAP 主机（可选）'
                  : 'IMAP 主机'
              }
              placeholder={
                importProvider === 'custom'
                  ? '必填，或在文本每行内嵌主机/端口'
                  : '可选'
              }
            />
            <ProFormDigit
              name="imap_port"
              label="IMAP 端口"
              min={1}
              max={65535}
              fieldProps={{ precision: 0 }}
            />
          </>
        )}
        <ProFormSwitch name="add_to_pool" label="同时加入邮箱池" />
      </ModalForm>

      <Modal
        title={`编辑账号 · ${editing?.email || ''}`}
        open={!!editing}
        confirmLoading={editLoading}
        destroyOnHidden
        width={640}
        onCancel={() => {
          setEditing(null);
          setEditAccountType('outlook');
          editForm.resetFields();
        }}
        onOk={async () => {
          if (!editing) return;
          try {
            const values = await editForm.validateFields();
            const body: Record<string, any> = {
              email: String(values.email || '').trim(),
              group_id: values.group_id,
              remark: values.remark || '',
              status: values.status || 'active',
            };
            if (values.password) body.password = values.password;
            if (values.client_id) body.client_id = values.client_id;
            if (values.refresh_token) body.refresh_token = values.refresh_token;

            const res = await updateAccount(editing.id, body);
            if (res?.success === false) {
              message.error(pickAccountErrorMessage(res, '更新失败'));
              return;
            }
            message.success(res.message || '账号更新成功');
            setEditing(null);
            editForm.resetFields();
            actionRef.current?.reload();
          } catch (error: any) {
            if (error?.errorFields) return;
            message.error(
              pickAccountErrorMessage(
                error?.response?.data,
                error?.message || '更新失败',
              ),
            );
          }
        }}
      >
        <Form form={editForm} layout="vertical" disabled={editLoading}>
          <Form.Item name="account_type" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[{ required: true, message: '邮箱不能为空' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={isImapEdit ? '授权码 / 应用密码' : '密码'}
            extra="留空则不修改"
          >
            <Input.Password placeholder="留空则不修改" />
          </Form.Item>
          {!isImapEdit ? (
            <>
              <Form.Item name="client_id" label="Client ID">
                <Input />
              </Form.Item>
              <Form.Item
                name="refresh_token"
                label="Refresh Token"
                extra="留空则不修改；修改 Client ID 时必须同时填写"
              >
                <Input.Password placeholder="留空则不修改" />
              </Form.Item>
            </>
          ) : null}
          <Form.Item
            name="group_id"
            label="分组"
            rules={[{ required: true, message: '请选择分组' }]}
          >
            <Select options={groupOptions} loading={groupsQuery.isLoading} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={ACCOUNT_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="导出账号（二次验证）"
        open={exportOpen}
        confirmLoading={exporting}
        onCancel={() => {
          setExportOpen(false);
          setExportPassword('');
        }}
        onOk={() => void onExport()}
        okText="验证并导出"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <div>
            <Typography.Text>选择分组</Typography.Text>
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: 8 }}
              options={groupOptions}
              value={exportGroupIds}
              onChange={setExportGroupIds}
              placeholder="选择要导出的分组"
            />
          </div>
          <div>
            <Typography.Text>登录密码</Typography.Text>
            <Input.Password
              style={{ marginTop: 8 }}
              value={exportPassword}
              onChange={(e) => setExportPassword(e.target.value)}
              placeholder="二次验证，防止误导出敏感凭据"
            />
          </div>
        </Space>
      </Modal>
    </PageContainer>
  );
};

export default AccountsPage;
