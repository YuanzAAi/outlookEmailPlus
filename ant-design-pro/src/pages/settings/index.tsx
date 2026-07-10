import { DeleteOutlined, PlusOutlined, SyncOutlined } from '@ant-design/icons';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIntl } from '@umijs/max';
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import React, { useEffect, useState } from 'react';
import {
  fetchDeploymentInfo,
  fetchSettings,
  pickSettingsError,
  syncCfWorkerDomains,
  testEmailNotification,
  testTelegram,
  testVerificationAi,
  testWebhook,
  triggerSystemUpdate,
  updateSettings,
  validateCron,
  type ExternalApiKeyItem,
} from '@/services/outlook/settings';

type KeyRow = ExternalApiKeyItem & { _localId: string };

const newLocalId = () =>
  `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

const SettingsPage: React.FC = () => {
  const { message, modal } = App.useApp();
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [keyRows, setKeyRows] = useState<KeyRow[]>([]);
  const [originalKeysCanonical, setOriginalKeysCanonical] = useState('[]');
  const [deployment, setDeployment] = useState<Record<string, any> | null>(
    null,
  );
  const [deploymentLoading, setDeploymentLoading] = useState(false);
  const [updateLoading, setUpdateLoading] = useState(false);
  const [cfSyncLoading, setCfSyncLoading] = useState(false);

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  });

  // 后端 GET 返回脱敏占位；PUT 时若值仍等于脱敏串则视为未修改（后端会跳过）
  const [secretMasks, setSecretMasks] = useState<Record<string, string>>({});

  useEffect(() => {
    const s = settingsQuery.data?.settings;
    if (!s) return;
    const masks: Record<string, string> = {
      telegram_bot_token: String(s.telegram_bot_token || ''),
      webhook_notification_token: String(s.webhook_notification_token || ''),
      verification_ai_api_key: String(s.verification_ai_api_key_masked || ''),
      temp_mail_api_key: String(s.temp_mail_api_key_masked || ''),
      external_api_key: String(s.external_api_key_masked || ''),
      cf_worker_admin_key: String(s.cf_worker_admin_key_masked || ''),
      watchtower_token: String(s.watchtower_token || ''),
    };
    setSecretMasks(masks);

    const keys: KeyRow[] = (Array.isArray(s.external_api_keys)
      ? s.external_api_keys
      : []
    ).map((item: ExternalApiKeyItem) => ({
      ...item,
      api_key: item.api_key || item.api_key_masked || '',
      allowed_emails: Array.isArray(item.allowed_emails)
        ? item.allowed_emails
        : typeof item.allowed_emails === 'string' && item.allowed_emails
          ? item.allowed_emails
              .split(/[\n,]/)
              .map((x) => x.trim())
              .filter(Boolean)
          : [],
      _localId: item.id != null ? `id_${item.id}` : newLocalId(),
    }));
    setKeyRows(keys);
    setOriginalKeysCanonical(
      JSON.stringify(
        keys.map((k) => ({
          id: k.id,
          name: k.name || '',
          api_key: k.api_key || '',
          enabled: k.enabled !== false,
          pool_access: !!k.pool_access,
          allowed_emails: k.allowed_emails || [],
        })),
      ),
    );

    const whitelist = Array.isArray(s.external_api_ip_whitelist)
      ? s.external_api_ip_whitelist.join('\n')
      : typeof s.external_api_ip_whitelist === 'string'
        ? s.external_api_ip_whitelist
        : '';

    form.setFieldsValue({
      enable_scheduled_refresh:
        s.enable_scheduled_refresh === 'true' ||
        s.enable_scheduled_refresh === true,
      use_cron_schedule:
        s.use_cron_schedule === 'true' || s.use_cron_schedule === true,
      refresh_cron: s.refresh_cron || '0 2 * * *',
      refresh_interval_days: Number(s.refresh_interval_days || 30),
      refresh_delay_seconds: Number(s.refresh_delay_seconds || 5),
      enable_auto_polling: !!s.enable_auto_polling,
      polling_interval: Number(s.polling_interval || 10),
      polling_count: Number(s.polling_count || 5),
      email_notification_enabled: !!s.email_notification_enabled,
      email_notification_recipient: s.email_notification_recipient || '',
      webhook_notification_enabled: !!s.webhook_notification_enabled,
      webhook_notification_url: s.webhook_notification_url || '',
      webhook_notification_token: masks.webhook_notification_token,
      telegram_bot_token: masks.telegram_bot_token,
      telegram_chat_id: s.telegram_chat_id || '',
      telegram_poll_interval: Number(s.telegram_poll_interval || 600),
      telegram_proxy_url: s.telegram_proxy_url || '',
      verification_ai_enabled: !!s.verification_ai_enabled,
      verification_ai_base_url: s.verification_ai_base_url || '',
      verification_ai_model: s.verification_ai_model || '',
      verification_ai_api_key: masks.verification_ai_api_key,
      temp_mail_provider: s.temp_mail_provider || '',
      temp_mail_api_base_url: s.temp_mail_api_base_url || '',
      temp_mail_api_key: masks.temp_mail_api_key,
      cf_worker_base_url: s.cf_worker_base_url || '',
      cf_worker_admin_key: masks.cf_worker_admin_key,
      external_api_public_mode: !!s.external_api_public_mode,
      external_api_rate_limit_per_minute: Number(
        s.external_api_rate_limit_per_minute || 60,
      ),
      external_api_key: masks.external_api_key,
      external_api_ip_whitelist_text: whitelist,
      external_api_disable_raw_content: !!s.external_api_disable_raw_content,
      external_api_disable_wait_message: !!s.external_api_disable_wait_message,
      external_api_disable_pool_claim_random:
        !!s.external_api_disable_pool_claim_random,
      external_api_disable_pool_claim_release:
        !!s.external_api_disable_pool_claim_release,
      external_api_disable_pool_claim_complete:
        !!s.external_api_disable_pool_claim_complete,
      external_api_disable_pool_stats: !!s.external_api_disable_pool_stats,
      pool_external_enabled: !!s.pool_external_enabled,
      watchtower_url: s.watchtower_url || '',
      watchtower_token: masks.watchtower_token,
      update_method: s.update_method || 'watchtower',
      login_password: '',
    });
  }, [settingsQuery.data, form]);

  const buildKeysPayload = (): ExternalApiKeyItem[] | null => {
    const normalized = keyRows.map((k) => ({
      id: k.id,
      name: String(k.name || '').trim(),
      api_key: String(k.api_key || '').trim(),
      enabled: k.enabled !== false,
      pool_access: !!k.pool_access,
      allowed_emails: Array.isArray(k.allowed_emails)
        ? k.allowed_emails
        : String(k.allowed_emails || '')
            .split(/[\n,]/)
            .map((x) => x.trim())
            .filter(Boolean),
    }));
    const canonical = JSON.stringify(normalized);
    if (canonical === originalKeysCanonical) {
      return null; // 未改动，不提交
    }
    for (const [i, item] of normalized.entries()) {
      if (!item.name) {
        throw new Error(`多 Key 第 ${i + 1} 项 name 不能为空`);
      }
      if (item.id == null && !item.api_key) {
        throw new Error(`多 Key「${item.name}」新建时 api_key 必填`);
      }
    }
    return normalized;
  };

  const onSave = async () => {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;
    setSaving(true);
    try {
      const payload: Record<string, any> = {
        ...values,
        enable_scheduled_refresh: values.enable_scheduled_refresh
          ? 'true'
          : 'false',
        use_cron_schedule: values.use_cron_schedule ? 'true' : 'false',
      };

      // 敏感字段：空串 / 仍等于脱敏占位 → 不提交，避免误清空
      const secretKeys = [
        'telegram_bot_token',
        'webhook_notification_token',
        'verification_ai_api_key',
        'temp_mail_api_key',
        'external_api_key',
        'cf_worker_admin_key',
        'watchtower_token',
        'login_password',
      ] as const;
      for (const key of secretKeys) {
        const raw = String(values[key] ?? '').trim();
        const mask = String(secretMasks[key] || '');
        if (!raw || (mask && raw === mask)) {
          delete payload[key];
        }
      }

      // IP 白名单：文本 → string[]
      const wlText = String(values.external_api_ip_whitelist_text || '');
      payload.external_api_ip_whitelist = wlText
        .split('\n')
        .map((l: string) => l.trim())
        .filter(Boolean);
      delete payload.external_api_ip_whitelist_text;

      try {
        const keysPayload = buildKeysPayload();
        if (keysPayload) {
          payload.external_api_keys = keysPayload;
        }
      } catch (e: any) {
        message.error(e?.message || '多 Key 配置无效');
        return;
      }

      const res = await updateSettings(payload);
      if (res?.success === false) {
        message.error(pickSettingsError(res, '保存失败'));
        return;
      }
      message.success(res.message || '设置已保存');
      form.setFieldValue('login_password', '');
      await queryClient.invalidateQueries({ queryKey: ['settings'] });
    } catch (error: any) {
      message.error(
        pickSettingsError(
          error?.data || error?.info || error?.response?.data,
          error?.message || '保存失败',
        ),
      );
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (
    fn: () => Promise<any>,
    okText = '测试成功',
    failText = '测试失败',
  ) => {
    try {
      const res = await fn();
      if (res?.success === false) {
        message.error(pickSettingsError(res, failText));
        return;
      }
      message.success(res?.message || okText);
    } catch (error: any) {
      message.error(
        pickSettingsError(
          error?.data || error?.info || error?.response?.data,
          error?.message || failText,
        ),
      );
    }
  };

  const loadDeployment = async () => {
    setDeploymentLoading(true);
    try {
      const res = await fetchDeploymentInfo();
      if (res?.success === false) {
        message.error(pickSettingsError(res, '获取部署信息失败'));
        return;
      }
      setDeployment(res.deployment || null);
    } catch (error: any) {
      message.error(error?.message || '获取部署信息失败');
    } finally {
      setDeploymentLoading(false);
    }
  };

  const onTriggerUpdate = () => {
    const method = form.getFieldValue('update_method') || 'watchtower';
    modal.confirm({
      title: '确认触发系统更新？',
      content: `将使用 method=${method} 调用 /api/system/trigger-update`,
      onOk: async () => {
        setUpdateLoading(true);
        try {
          const res = await triggerSystemUpdate(String(method));
          if (res?.success === false) {
            message.error(pickSettingsError(res, '触发更新失败'));
            return;
          }
          message.success(res.message || '已触发更新');
          await loadDeployment();
        } catch (error: any) {
          message.error(error?.message || '触发更新失败');
        } finally {
          setUpdateLoading(false);
        }
      },
    });
  };

  const onSyncCfDomains = async () => {
    setCfSyncLoading(true);
    try {
      const res = await syncCfWorkerDomains();
      if (res?.success === false) {
        message.error(pickSettingsError(res, 'CF 域名同步失败'));
        return;
      }
      message.success(res.message || 'CF 域名同步成功');
      await queryClient.invalidateQueries({ queryKey: ['settings'] });
    } catch (error: any) {
      message.error(error?.message || 'CF 域名同步失败');
    } finally {
      setCfSyncLoading(false);
    }
  };

  const updateKeyRow = (localId: string, patch: Partial<KeyRow>) => {
    setKeyRows((rows) =>
      rows.map((r) => (r._localId === localId ? { ...r, ...patch } : r)),
    );
  };

  const sMeta = settingsQuery.data?.settings || {};

  return (
    <PageContainer
      title={intl.formatMessage({
        id: 'outlook.settings.title',
        defaultMessage: '系统设置',
      })}
      subTitle={intl.formatMessage({
        id: 'outlook.settings.subtitle',
        defaultMessage: '对接 /api/settings · 多 Key / 白名单 / CF / 部署',
      })}
      extra={
        <Space>
          <Button
            loading={settingsQuery.isFetching}
            onClick={() =>
              void queryClient.invalidateQueries({ queryKey: ['settings'] })
            }
          >
            重新加载
          </Button>
          <Button type="primary" loading={saving} onClick={() => void onSave()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" disabled={settingsQuery.isLoading}>
        <Tabs
          items={[
            {
              key: 'refresh',
              label: 'Token 刷新',
              children: (
                <ProCard bordered>
                  <Form.Item
                    name="enable_scheduled_refresh"
                    label="启用定时刷新"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="use_cron_schedule"
                    label="使用 Cron 表达式"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="refresh_cron" label="Cron">
                    <Input
                      addonAfter={
                        <Button
                          type="link"
                          size="small"
                          onClick={async () => {
                            const cron = form.getFieldValue('refresh_cron');
                            await runTest(
                              () => validateCron(String(cron || '')),
                              'Cron 有效',
                              'Cron 无效',
                            );
                          }}
                        >
                          校验
                        </Button>
                      }
                    />
                  </Form.Item>
                  <Form.Item name="refresh_interval_days" label="刷新间隔（天）">
                    <InputNumber min={1} max={365} style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item name="refresh_delay_seconds" label="账号间延迟（秒）">
                    <InputNumber min={0} max={3600} style={{ width: '100%' }} />
                  </Form.Item>
                </ProCard>
              ),
            },
            {
              key: 'polling',
              label: '轮询',
              children: (
                <ProCard bordered>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="SPA 已提供最小轮询引擎"
                    description="邮箱页「开始监听」会按本页 interval/count 调用列表与 extract-verification；以下开关仍写入后端 settings，供持久化与旧前端兼容。"
                  />
                  <Form.Item
                    name="enable_auto_polling"
                    label="自动轮询（后端配置）"
                    valuePropName="checked"
                    extra="持久化设置；SPA 侧在邮箱页手动启动监听"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="polling_interval" label="间隔（秒）">
                    <InputNumber min={1} max={3600} style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item name="polling_count" label="次数">
                    <InputNumber min={1} max={100} style={{ width: '100%' }} />
                  </Form.Item>
                </ProCard>
              ),
            },
            {
              key: 'notify',
              label: '通知',
              children: (
                <ProCard bordered>
                  <Typography.Title level={5}>邮件</Typography.Title>
                  <Form.Item
                    name="email_notification_enabled"
                    label="启用邮件通知"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="email_notification_recipient" label="收件人">
                    <Input />
                  </Form.Item>
                  <Button
                    style={{ marginBottom: 16 }}
                    onClick={() =>
                      void runTest(testEmailNotification, '邮件测试成功')
                    }
                  >
                    测试邮件
                  </Button>

                  <Typography.Title level={5}>Webhook</Typography.Title>
                  <Form.Item
                    name="webhook_notification_enabled"
                    label="启用 Webhook"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="webhook_notification_url" label="Webhook URL">
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="webhook_notification_token"
                    label="Webhook Token"
                    extra="显示脱敏值；改写后保存才会更新，留空不改"
                  >
                    <Input.Password
                      visibilityToggle
                      placeholder="脱敏展示 / 输入新 Token"
                    />
                  </Form.Item>
                  <Button
                    style={{ marginBottom: 16 }}
                    onClick={() =>
                      void runTest(() => testWebhook({}), 'Webhook 测试成功')
                    }
                  >
                    测试 Webhook
                  </Button>

                  <Typography.Title level={5}>Telegram</Typography.Title>
                  <Form.Item
                    name="telegram_bot_token"
                    label="Bot Token"
                    extra="后端返回脱敏值（****后四位）；仅在输入新值时更新"
                  >
                    <Input.Password visibilityToggle placeholder="****xxxx" />
                  </Form.Item>
                  <Form.Item name="telegram_chat_id" label="Chat ID">
                    <Input />
                  </Form.Item>
                  <Form.Item name="telegram_poll_interval" label="轮询间隔（秒）">
                    <InputNumber min={10} max={86400} style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item name="telegram_proxy_url" label="代理 URL">
                    <Input />
                  </Form.Item>
                  <Button
                    onClick={() => void runTest(testTelegram, 'Telegram 测试成功')}
                  >
                    测试 Telegram
                  </Button>
                </ProCard>
              ),
            },
            {
              key: 'ai',
              label: '验证码 AI',
              children: (
                <ProCard bordered>
                  <Form.Item
                    name="verification_ai_enabled"
                    label="启用 AI 增强"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="verification_ai_base_url" label="Base URL">
                    <Input />
                  </Form.Item>
                  <Form.Item name="verification_ai_model" label="模型">
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="verification_ai_api_key"
                    label="API Key"
                    extra={
                      sMeta.verification_ai_api_key_set
                        ? `已设置：${sMeta.verification_ai_api_key_masked || ''}`
                        : '未设置'
                    }
                  >
                    <Input.Password
                      visibilityToggle
                      placeholder="输入新 Key 以更新"
                    />
                  </Form.Item>
                  <Button
                    onClick={() =>
                      void runTest(() => testVerificationAi({}), 'AI 连通性正常')
                    }
                  >
                    测试 AI
                  </Button>
                </ProCard>
              ),
            },
            {
              key: 'external',
              label: '外部 API / 池',
              children: (
                <ProCard bordered>
                  <Form.Item
                    name="external_api_public_mode"
                    label="公网模式"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_rate_limit_per_minute"
                    label="每分钟限流"
                  >
                    <InputNumber min={1} max={10000} style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item
                    name="external_api_key"
                    label="对外 API Key（单 Key 兼容）"
                    extra={
                      sMeta.external_api_key_set
                        ? `已设置：${sMeta.external_api_key_masked || ''}`
                        : '未设置'
                    }
                  >
                    <Input.Password
                      visibilityToggle
                      placeholder="输入新 Key 以更新"
                    />
                  </Form.Item>

                  <Typography.Title level={5}>
                    多 Key（external_api_keys）
                  </Typography.Title>
                  <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
                    保留脱敏 api_key 表示不修改；新建必须填明文 Key；保存时若未改动则不提交本字段。
                  </Typography.Paragraph>
                  <Table<KeyRow>
                    size="small"
                    rowKey="_localId"
                    pagination={false}
                    style={{ marginBottom: 12 }}
                    dataSource={keyRows}
                    columns={[
                      {
                        title: '名称',
                        dataIndex: 'name',
                        width: 140,
                        render: (_, row) => (
                          <Input
                            size="small"
                            value={row.name}
                            onChange={(e) =>
                              updateKeyRow(row._localId, {
                                name: e.target.value,
                              })
                            }
                          />
                        ),
                      },
                      {
                        title: 'API Key',
                        dataIndex: 'api_key',
                        render: (_, row) => (
                          <Input.Password
                            size="small"
                            value={row.api_key}
                            placeholder="脱敏保留=不改"
                            onChange={(e) =>
                              updateKeyRow(row._localId, {
                                api_key: e.target.value,
                              })
                            }
                          />
                        ),
                      },
                      {
                        title: '邮箱范围',
                        dataIndex: 'allowed_emails',
                        width: 180,
                        render: (_, row) => (
                          <Input.TextArea
                            size="small"
                            rows={2}
                            value={
                              Array.isArray(row.allowed_emails)
                                ? row.allowed_emails.join('\n')
                                : String(row.allowed_emails || '')
                            }
                            placeholder="每行一个邮箱，空=不限"
                            onChange={(e) =>
                              updateKeyRow(row._localId, {
                                allowed_emails: e.target.value
                                  .split(/[\n,]/)
                                  .map((x) => x.trim())
                                  .filter(Boolean),
                              })
                            }
                          />
                        ),
                      },
                      {
                        title: '池权限',
                        dataIndex: 'pool_access',
                        width: 80,
                        render: (_, row) => (
                          <Switch
                            size="small"
                            checked={!!row.pool_access}
                            onChange={(v) =>
                              updateKeyRow(row._localId, { pool_access: v })
                            }
                          />
                        ),
                      },
                      {
                        title: '启用',
                        dataIndex: 'enabled',
                        width: 70,
                        render: (_, row) => (
                          <Switch
                            size="small"
                            checked={row.enabled !== false}
                            onChange={(v) =>
                              updateKeyRow(row._localId, { enabled: v })
                            }
                          />
                        ),
                      },
                      {
                        title: '',
                        width: 48,
                        render: (_, row) => (
                          <Button
                            type="text"
                            danger
                            size="small"
                            icon={<DeleteOutlined />}
                            onClick={() =>
                              setKeyRows((rows) =>
                                rows.filter((r) => r._localId !== row._localId),
                              )
                            }
                          />
                        ),
                      },
                    ]}
                  />
                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    style={{ marginBottom: 16 }}
                    onClick={() =>
                      setKeyRows((rows) => [
                        ...rows,
                        {
                          _localId: newLocalId(),
                          name: '',
                          api_key: '',
                          enabled: true,
                          pool_access: false,
                          allowed_emails: [],
                        },
                      ])
                    }
                  >
                    添加 Key
                  </Button>
                  <Button
                    danger
                    type="link"
                    onClick={() => setKeyRows([])}
                    disabled={!keyRows.length}
                  >
                    清空全部多 Key
                  </Button>

                  <Form.Item
                    name="external_api_ip_whitelist_text"
                    label="IP 白名单"
                    extra="每行一个 IP / CIDR；空表示不限制"
                  >
                    <Input.TextArea rows={4} placeholder="127.0.0.1&#10;10.0.0.0/8" />
                  </Form.Item>

                  <Typography.Title level={5}>危险端点开关</Typography.Title>
                  <Form.Item
                    name="external_api_disable_raw_content"
                    label="禁用 raw content"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_disable_wait_message"
                    label="禁用 wait message"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_disable_pool_claim_random"
                    label="禁用 pool claim random"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_disable_pool_claim_release"
                    label="禁用 pool claim release"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_disable_pool_claim_complete"
                    label="禁用 pool claim complete"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="external_api_disable_pool_stats"
                    label="禁用 pool stats"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>

                  <Form.Item
                    name="pool_external_enabled"
                    label="启用外部邮箱池"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="temp_mail_provider" label="临时邮箱 Provider">
                    <Input />
                  </Form.Item>
                  <Form.Item name="temp_mail_api_base_url" label="临时邮箱 API Base">
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="temp_mail_api_key"
                    label="临时邮箱 API Key"
                    extra={
                      sMeta.temp_mail_api_key_set
                        ? `已设置：${sMeta.temp_mail_api_key_masked || ''}`
                        : '未设置'
                    }
                  >
                    <Input.Password
                      visibilityToggle
                      placeholder="输入新 Key 以更新"
                    />
                  </Form.Item>
                  <Form.Item name="cf_worker_base_url" label="CF Worker Base">
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="cf_worker_admin_key"
                    label="CF Worker Admin Key"
                    extra={
                      sMeta.cf_worker_admin_key_set
                        ? `已设置：${sMeta.cf_worker_admin_key_masked || ''}`
                        : '未设置'
                    }
                  >
                    <Input.Password
                      visibilityToggle
                      placeholder="输入新 Key 以更新"
                    />
                  </Form.Item>
                  <Space>
                    <Button
                      icon={<SyncOutlined />}
                      loading={cfSyncLoading}
                      onClick={() => void onSyncCfDomains()}
                    >
                      同步 CF Worker 域名
                    </Button>
                    {Array.isArray(sMeta.cf_worker_domains) &&
                    sMeta.cf_worker_domains.length ? (
                      <Typography.Text type="secondary">
                        当前域：{sMeta.cf_worker_domains.join(', ')}
                      </Typography.Text>
                    ) : null}
                  </Space>
                </ProCard>
              ),
            },
            {
              key: 'security',
              label: '安全',
              children: (
                <ProCard bordered>
                  <Form.Item
                    name="login_password"
                    label="修改登录密码"
                    extra={
                      sMeta.allow_login_password_change === false
                        ? '当前站点已禁用密码修改（ALLOW_LOGIN_PASSWORD_CHANGE）'
                        : sMeta.login_password_set
                          ? '已设置登录密码；留空表示不修改'
                          : '尚未设置登录密码'
                    }
                  >
                    <Input.Password
                      visibilityToggle
                      disabled={sMeta.allow_login_password_change === false}
                      placeholder="至少 8 位；留空不修改"
                    />
                  </Form.Item>
                </ProCard>
              ),
            },
            {
              key: 'update',
              label: '更新 / 部署',
              children: (
                <ProCard bordered>
                  <Form.Item name="update_method" label="更新方式">
                    <Select
                      options={[
                        { label: 'watchtower', value: 'watchtower' },
                        { label: 'docker_api', value: 'docker_api' },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item name="watchtower_url" label="Watchtower URL">
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="watchtower_token"
                    label="Watchtower Token"
                    extra="显示脱敏值；改写后保存才会更新"
                  >
                    <Input.Password visibilityToggle placeholder="****xxxx" />
                  </Form.Item>
                  <Space wrap style={{ marginBottom: 16 }}>
                    <Button
                      loading={deploymentLoading}
                      onClick={() => void loadDeployment()}
                    >
                      刷新部署信息
                    </Button>
                    <Button
                      type="primary"
                      danger
                      loading={updateLoading}
                      onClick={onTriggerUpdate}
                    >
                      触发更新
                    </Button>
                  </Space>
                  {deployment ? (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <div>
                        <Typography.Text type="secondary">镜像：</Typography.Text>{' '}
                        {String(deployment.image || 'unknown')}
                      </div>
                      <div>
                        <Typography.Text type="secondary">可自动更新：</Typography.Text>{' '}
                        {deployment.can_auto_update ? (
                          <Tag color="success">是</Tag>
                        ) : (
                          <Tag>否</Tag>
                        )}
                        <Typography.Text type="secondary" style={{ marginLeft: 12 }}>
                          推荐：
                        </Typography.Text>{' '}
                        {String(deployment.recommended_method || '--')}
                      </div>
                      <div>
                        <Typography.Text type="secondary">Watchtower：</Typography.Text>{' '}
                        {deployment.watchtower_reachable == null
                          ? '--'
                          : deployment.watchtower_reachable
                            ? '可达'
                            : '不可达'}
                        <Typography.Text type="secondary" style={{ marginLeft: 12 }}>
                          Docker API：
                        </Typography.Text>{' '}
                        {deployment.docker_api_available ? '可用' : '不可用'}
                      </div>
                      {Array.isArray(deployment.warnings) &&
                      deployment.warnings.length ? (
                        <Alert
                          type="warning"
                          showIcon
                          message="部署警告"
                          description={
                            <ul style={{ margin: 0, paddingLeft: 18 }}>
                              {deployment.warnings.map((w: any, i: number) => (
                                <li key={i}>{String(w)}</li>
                              ))}
                            </ul>
                          }
                        />
                      ) : null}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">
                      点击「刷新部署信息」拉取 /api/system/deployment-info
                    </Typography.Text>
                  )}
                </ProCard>
              ),
            },
          ]}
        />
      </Form>
    </PageContainer>
  );
};

export default SettingsPage;
