import { PageContainer, ProCard } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Tabs,
  Typography,
} from 'antd';
import React, { useEffect, useState } from 'react';
import {
  fetchSettings,
  pickSettingsError,
  testEmailNotification,
  testTelegram,
  testVerificationAi,
  testWebhook,
  updateSettings,
  validateCron,
} from '@/services/outlook/settings';

const SettingsPage: React.FC = () => {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

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
      pool_external_enabled: !!s.pool_external_enabled,
      watchtower_url: s.watchtower_url || '',
      watchtower_token: masks.watchtower_token,
      update_method: s.update_method || 'watchtower',
      login_password: '',
    });
  }, [settingsQuery.data, form]);

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

  const sMeta = settingsQuery.data?.settings || {};

  return (
    <PageContainer
      title="系统设置"
      subTitle="对接 /api/settings"
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
                  <Form.Item
                    name="enable_auto_polling"
                    label="自动轮询"
                    valuePropName="checked"
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
                    <Input.Password visibilityToggle placeholder="脱敏展示 / 输入新 Token" />
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
                    label="对外 API Key（单 Key）"
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
              label: '更新',
              children: (
                <ProCard bordered>
                  <Form.Item name="update_method" label="更新方式">
                    <Input placeholder="watchtower / docker_api" />
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
