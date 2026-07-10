import {
  ApiOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  ModalForm,
  PageContainer,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from 'antd';
import React, { useRef, useState } from 'react';
import {
  fetchPluginConfig,
  fetchPluginConfigSchema,
  fetchPlugins,
  installPlugin,
  pickPluginErrorMessage,
  reloadPlugins,
  savePluginConfig,
  testPluginConnection,
  uninstallPlugin,
  type PluginItem,
} from '@/services/outlook/plugins';

const statusTag = (status?: string) => {
  if (status === 'installed') return <Tag color="success">已安装</Tag>;
  if (status === 'load_failed') return <Tag color="error">加载失败</Tag>;
  return <Tag color="processing">可安装</Tag>;
};

const PluginsPage: React.FC = () => {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const actionRef = useRef<ActionType>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [configPlugin, setConfigPlugin] = useState<PluginItem | null>(null);
  const [configFields, setConfigFields] = useState<
    Array<{ key: string; label?: string; type?: string; required?: boolean }>
  >([]);
  const [configLoading, setConfigLoading] = useState(false);
  const [configForm] = Form.useForm();

  const pluginsQuery = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
  });

  const plugins = pluginsQuery.data?.data?.plugins || [];
  const installedCount = pluginsQuery.data?.data?.installed_count ?? 0;

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: ['plugins'] });
    actionRef.current?.reload();
  };

  const openConfig = async (plugin: PluginItem) => {
    setConfigPlugin(plugin);
    setConfigLoading(true);
    try {
      const [schemaRes, configRes] = await Promise.all([
        fetchPluginConfigSchema(plugin.name),
        fetchPluginConfig(plugin.name),
      ]);
      if (schemaRes?.success === false) {
        message.error(pickPluginErrorMessage(schemaRes, '读取 schema 失败'));
        setConfigPlugin(null);
        return;
      }
      if (configRes?.success === false) {
        message.error(pickPluginErrorMessage(configRes, '读取配置失败'));
        setConfigPlugin(null);
        return;
      }
      const fields = schemaRes?.data?.fields || [];
      setConfigFields(fields);
      configForm.setFieldsValue(configRes?.data || {});
    } catch (error: any) {
      message.error(
        pickPluginErrorMessage(error?.response?.data, error?.message || '加载配置失败'),
      );
      setConfigPlugin(null);
    } finally {
      setConfigLoading(false);
    }
  };

  const columns: ProColumns<PluginItem>[] = [
    {
      title: '名称',
      dataIndex: 'display_name',
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{row.display_name || row.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.name}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 100,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '作者',
      dataIndex: 'author',
      width: 120,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      search: false,
      render: (_, row) => statusTag(row.status),
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '操作',
      valueType: 'option',
      width: 280,
      render: (_, row) => {
        const actions: React.ReactNode[] = [];
        if (row.status === 'available') {
          actions.push(
            <Button
              key="install"
              type="link"
              icon={<DownloadOutlined />}
              onClick={async () => {
                try {
                  const res = await installPlugin({ name: row.name });
                  if (res?.success === false) {
                    message.error(pickPluginErrorMessage(res, '安装失败'));
                    return;
                  }
                  message.success(res.message || '安装成功');
                  await reload();
                } catch (error: any) {
                  message.error(
                    pickPluginErrorMessage(
                      error?.response?.data,
                      error?.message || '安装失败',
                    ),
                  );
                }
              }}
            >
              安装
            </Button>,
          );
        }
        if (row.status === 'installed' || row.status === 'load_failed') {
          if (row.status === 'installed') {
            actions.push(
              <Button
                key="cfg"
                type="link"
                icon={<SettingOutlined />}
                onClick={() => void openConfig(row)}
              >
                配置
              </Button>,
            );
            actions.push(
              <Button
                key="test"
                type="link"
                icon={<ApiOutlined />}
                onClick={async () => {
                  try {
                    const res = await testPluginConnection(row.name);
                    if (res?.success === false) {
                      message.error(pickPluginErrorMessage(res, '连接失败'));
                      return;
                    }
                    message.success(res.message || '连接成功');
                  } catch (error: any) {
                    message.error(
                      pickPluginErrorMessage(
                        error?.response?.data,
                        error?.message || '连接失败',
                      ),
                    );
                  }
                }}
              >
                测试
              </Button>,
            );
          }
          actions.push(
            <Popconfirm
              key="uninstall"
              title={`确认卸载 ${row.display_name || row.name}？`}
              onConfirm={async () => {
                try {
                  const res = await uninstallPlugin(row.name, false);
                  if (res?.success === false) {
                    message.error(pickPluginErrorMessage(res, '卸载失败'));
                    return;
                  }
                  message.success(res.message || '已卸载');
                  await reload();
                } catch (error: any) {
                  message.error(
                    pickPluginErrorMessage(
                      error?.response?.data,
                      error?.message || '卸载失败',
                    ),
                  );
                }
              }}
            >
              <Button type="link" danger icon={<DeleteOutlined />}>
                卸载
              </Button>
            </Popconfirm>,
          );
        }
        return actions;
      },
    },
  ];

  return (
    <PageContainer
      title="插件管理"
      subTitle={`对接 /api/plugins · 已安装 ${installedCount}`}
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            loading={pluginsQuery.isFetching}
            onClick={() => void reload()}
          >
            刷新
          </Button>
          <Button onClick={() => setCustomOpen(true)}>自定义安装</Button>
          <Button
            type="primary"
            onClick={async () => {
              try {
                const res = await reloadPlugins();
                if (res?.success === false) {
                  message.error(pickPluginErrorMessage(res, '应用变更失败'));
                  return;
                }
                message.success(res.message || '已应用变更');
                await reload();
              } catch (error: any) {
                message.error(
                  pickPluginErrorMessage(
                    error?.response?.data,
                    error?.message || '应用变更失败',
                  ),
                );
              }
            }}
          >
            应用变更
          </Button>
        </Space>
      }
    >
      <ProTable<PluginItem>
        rowKey="name"
        actionRef={actionRef}
        columns={columns}
        search={false}
        loading={pluginsQuery.isLoading || pluginsQuery.isFetching}
        dataSource={plugins}
        pagination={{ pageSize: 20 }}
        options={false}
        toolBarRender={false}
        expandable={{
          expandedRowRender: (row) =>
            row.error ? (
              <Typography.Text type="danger">加载失败：{row.error}</Typography.Text>
            ) : (
              <Typography.Text type="secondary">
                {row.description || '无额外信息'}
              </Typography.Text>
            ),
          rowExpandable: (row) => !!row.error || !!row.description,
        }}
      />

      <ModalForm
        title="自定义安装插件"
        open={customOpen}
        modalProps={{ destroyOnHidden: true, onCancel: () => setCustomOpen(false) }}
        onOpenChange={setCustomOpen}
        onFinish={async (values) => {
          try {
            const res = await installPlugin({
              name: values.name,
              url: values.url,
            });
            if (res?.success === false) {
              message.error(pickPluginErrorMessage(res, '安装失败'));
              return false;
            }
            message.success(res.message || '安装成功');
            await reload();
            return true;
          } catch (error: any) {
            message.error(
              pickPluginErrorMessage(
                error?.response?.data,
                error?.message || '安装失败',
              ),
            );
            return false;
          }
        }}
      >
        <ProFormText
          name="name"
          label="插件名称"
          rules={[{ required: true, message: '请输入插件名称' }]}
        />
        <ProFormText name="url" label="下载 URL" placeholder="可选，覆盖默认源" />
      </ModalForm>

      <Modal
        title={`配置 · ${configPlugin?.display_name || configPlugin?.name || ''}`}
        open={!!configPlugin}
        confirmLoading={configLoading}
        destroyOnHidden
        onCancel={() => {
          setConfigPlugin(null);
          configForm.resetFields();
        }}
        onOk={async () => {
          if (!configPlugin) return;
          try {
            const values = await configForm.validateFields();
            const res = await savePluginConfig(configPlugin.name, values);
            if (res?.success === false) {
              message.error(pickPluginErrorMessage(res, '保存失败'));
              return;
            }
            message.success(res.message || '配置已保存');
            setConfigPlugin(null);
            configForm.resetFields();
          } catch (error: any) {
            if (error?.errorFields) return;
            message.error(
              pickPluginErrorMessage(
                error?.response?.data,
                error?.message || '保存失败',
              ),
            );
          }
        }}
      >
        <Form form={configForm} layout="vertical" disabled={configLoading}>
          {configFields.length === 0 ? (
            <Typography.Text type="secondary">
              {configLoading ? '加载中…' : '该插件无可配置字段'}
            </Typography.Text>
          ) : (
            configFields.map((field) => {
              const sensitive = /key|token|secret|password/i.test(field.key);
              return (
                <Form.Item
                  key={field.key}
                  name={field.key}
                  label={field.label || field.key}
                  rules={
                    field.required
                      ? [
                          {
                            required: true,
                            message: `请填写 ${field.label || field.key}`,
                          },
                        ]
                      : undefined
                  }
                >
                  {sensitive ? <Input.Password /> : <Input />}
                </Form.Item>
              );
            })
          )}
        </Form>
      </Modal>
    </PageContainer>
  );
};

export default PluginsPage;
