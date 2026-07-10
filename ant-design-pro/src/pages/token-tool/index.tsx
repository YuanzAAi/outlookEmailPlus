import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  App,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Typography,
} from 'antd';
import React, { useEffect, useState } from 'react';
import {
  exchangeToken,
  fetchTokenToolAccounts,
  fetchTokenToolConfig,
  pickTokenToolError,
  prepareOAuth,
  saveTokenToAccount,
  saveTokenToolConfig,
  type TokenResult,
  type TokenToolConfig,
} from '@/services/outlook/tokenTool';
import { useIntl } from '@umijs/max';

const DEFAULT_SCOPE =
  'https://graph.microsoft.com/Mail.Read offline_access openid profile';

const TokenToolPage: React.FC = () => {
  const { message } = App.useApp();
  const intl = useIntl();
  const [configForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [authorizeUrl, setAuthorizeUrl] = useState('');
  const [callbackUrl, setCallbackUrl] = useState('');
  const [tokenResult, setTokenResult] = useState<TokenResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveMode, setSaveMode] = useState<'update' | 'create'>('update');
  const [accounts, setAccounts] = useState<
    Array<{ id: number; email: string; status?: string }>
  >([]);
  const [accountId, setAccountId] = useState<number | undefined>();
  const [newEmail, setNewEmail] = useState('');

  const loadConfig = async () => {
    setLoading(true);
    try {
      const res = await fetchTokenToolConfig();
      if (res?.success === false) {
        message.error(pickTokenToolError(res, '加载配置失败'));
        return;
      }
      const cfg = res.data || {};
      configForm.setFieldsValue({
        client_id: cfg.client_id || '',
        redirect_uri:
          cfg.redirect_uri || `${window.location.origin}/token-tool/callback`,
        scope: cfg.scope || DEFAULT_SCOPE,
        prompt_consent: !!cfg.prompt_consent,
      });
    } catch (error: any) {
      message.error(
        pickTokenToolError(
          error?.response?.data,
          error?.message || '加载配置失败',
        ),
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const collectConfig = (): TokenToolConfig => {
    const values = configForm.getFieldsValue();
    return {
      client_id: values.client_id?.trim() || '',
      client_secret: '',
      redirect_uri: values.redirect_uri?.trim() || '',
      scope: values.scope?.trim() || DEFAULT_SCOPE,
      tenant: 'consumers',
      prompt_consent: !!values.prompt_consent,
    };
  };

  const onSaveConfig = async () => {
    try {
      const res = await saveTokenToolConfig(collectConfig());
      if (res?.success === false) {
        message.error(pickTokenToolError(res, '保存失败'));
        return;
      }
      message.success(res.message || '配置已保存');
    } catch (error: any) {
      message.error(
        pickTokenToolError(error?.response?.data, error?.message || '保存失败'),
      );
    }
  };

  const onPrepare = async () => {
    setLoading(true);
    try {
      const res = await prepareOAuth(collectConfig());
      if (res?.success === false) {
        message.error(pickTokenToolError(res, '生成授权链接失败'));
        return;
      }
      const url = res.data?.authorize_url || '';
      setAuthorizeUrl(url);
      if (!url) {
        message.error('授权地址为空');
        return;
      }
      message.success('授权链接已生成');
    } catch (error: any) {
      message.error(
        pickTokenToolError(error?.response?.data, error?.message || '生成失败'),
      );
    } finally {
      setLoading(false);
    }
  };

  const onExchange = async () => {
    if (!callbackUrl.trim()) {
      message.error('请粘贴回调 URL');
      return;
    }
    setLoading(true);
    try {
      const res = await exchangeToken(callbackUrl.trim());
      if (res?.success === false) {
        message.error(pickTokenToolError(res, '换取 Token 失败'));
        return;
      }
      setTokenResult(res.data || null);
      message.success('Token 换取成功');
    } catch (error: any) {
      message.error(
        pickTokenToolError(error?.response?.data, error?.message || '换取失败'),
      );
    } finally {
      setLoading(false);
    }
  };

  const openSave = async () => {
    if (!tokenResult?.refresh_token) {
      message.error('请先成功换取 Token');
      return;
    }
    setSaveOpen(true);
    try {
      const res = await fetchTokenToolAccounts();
      if (res?.success) {
        setAccounts(res.data || []);
      }
    } catch {
      // ignore
    }
  };

  const confirmSave = async () => {
    if (!tokenResult?.refresh_token) return;
    try {
      const body: any = {
        mode: saveMode,
        refresh_token: tokenResult.refresh_token,
        client_id:
          tokenResult.client_id || configForm.getFieldValue('client_id'),
      };
      if (saveMode === 'update') {
        if (!accountId) {
          message.error('请选择账号');
          return;
        }
        body.account_id = accountId;
      } else {
        if (!newEmail.trim()) {
          message.error('请输入新账号邮箱');
          return;
        }
        body.email = newEmail.trim();
      }
      const res = await saveTokenToAccount(body);
      if (res?.success === false) {
        message.error(pickTokenToolError(res, '写入失败'));
        return;
      }
      message.success(res.message || 'Token 已写入账号');
      setSaveOpen(false);
    } catch (error: any) {
      message.error(
        pickTokenToolError(error?.response?.data, error?.message || '写入失败'),
      );
    }
  };

  return (
    <PageContainer title={intl.formatMessage({
      id: 'outlook.tokenTool.title',
      defaultMessage: 'OAuth Token 工具',
    })} subTitle="对接 /api/token-tool/*">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <ProCard title="OAuth 配置" bordered loading={loading && !authorizeUrl}>
          <Form
            form={configForm}
            layout="vertical"
            initialValues={{ scope: DEFAULT_SCOPE }}
          >
            <Form.Item
              name="client_id"
              label="Client ID"
              rules={[{ required: true, message: '请输入 Client ID' }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="redirect_uri" label="Redirect URI">
              <Input />
            </Form.Item>
            <Form.Item name="scope" label="Scope">
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item
              name="prompt_consent"
              valuePropName="checked"
              label="强制同意提示"
            >
              <Checkbox>prompt=consent</Checkbox>
            </Form.Item>
            <Space wrap>
              <Button onClick={() => void onSaveConfig()}>保存配置</Button>
              <Button type="primary" loading={loading} onClick={() => void onPrepare()}>
                生成授权链接
              </Button>
            </Space>
          </Form>
        </ProCard>

        {authorizeUrl ? (
          <ProCard title="授权链接" bordered>
            <Input.TextArea rows={3} value={authorizeUrl} readOnly />
            <Space style={{ marginTop: 12 }}>
              <Button
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(authorizeUrl);
                    message.success('已复制');
                  } catch {
                    message.error('复制失败');
                  }
                }}
              >
                复制
              </Button>
              <Button type="primary" href={authorizeUrl} target="_blank">
                打开
              </Button>
            </Space>
          </ProCard>
        ) : null}

        <ProCard title="粘贴回调 URL 换取 Token" bordered>
          <Input.TextArea
            rows={3}
            placeholder="将浏览器地址栏的回调 URL 粘贴到这里"
            value={callbackUrl}
            onChange={(e) => setCallbackUrl(e.target.value)}
          />
          <Button
            type="primary"
            style={{ marginTop: 12 }}
            loading={loading}
            onClick={() => void onExchange()}
          >
            换取 Token
          </Button>
        </ProCard>

        {tokenResult ? (
          <ProCard
            title="Token 结果"
            bordered
            extra={
              <Button type="primary" onClick={() => void openSave()}>
                写入账号
              </Button>
            }
          >
            {(
              [
                ['refresh_token', tokenResult.refresh_token],
                ['access_token', tokenResult.access_token],
                ['client_id', tokenResult.client_id],
                ['granted_scope', tokenResult.granted_scope],
                ['expires_in', String(tokenResult.expires_in || '')],
              ] as Array<[string, string | undefined]>
            ).map(([key, value]) => (
              <div key={key} style={{ marginBottom: 8 }}>
                <Typography.Text type="secondary">{key}</Typography.Text>
                <Input.TextArea
                  rows={key.includes('token') ? 2 : 1}
                  value={value || ''}
                  readOnly
                />
              </div>
            ))}
          </ProCard>
        ) : null}
      </Space>

      <Modal
        title="写入账号"
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={() => void confirmSave()}
        destroyOnHidden
      >
        <Radio.Group
          value={saveMode}
          onChange={(e) => setSaveMode(e.target.value)}
          style={{ marginBottom: 16 }}
        >
          <Radio.Button value="update">更新已有账号</Radio.Button>
          <Radio.Button value="create">创建新账号</Radio.Button>
        </Radio.Group>
        {saveMode === 'update' ? (
          <Select
            style={{ width: '100%' }}
            placeholder="选择账号"
            value={accountId}
            onChange={setAccountId}
            options={accounts.map((a) => ({
              label: `${a.email} (${a.status || 'active'})`,
              value: a.id,
            }))}
          />
        ) : (
          <Input
            placeholder="新账号邮箱"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
        )}
      </Modal>
    </PageContainer>
  );
};

export default TokenToolPage;
