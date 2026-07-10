import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  ModalForm,
  PageContainer,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Popconfirm, Space, Tag } from 'antd';
import React, { useRef, useState } from 'react';
import {
  createGroup,
  deleteGroup,
  fetchGroups,
  isTempMailboxGroup,
  updateGroup,
  type GroupItem,
} from '@/services/outlook/groups';

const GroupsPage: React.FC = () => {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const actionRef = useRef<ActionType>(null);
  const [editing, setEditing] = useState<GroupItem | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const groupsQuery = useQuery({
    queryKey: ['groups'],
    queryFn: fetchGroups,
  });

  const dataSource = (groupsQuery.data?.groups || []).filter(
    (g) => !isTempMailboxGroup(g),
  );

  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: ['groups'] });
    actionRef.current?.reload();
  };

  const columns: ProColumns<GroupItem>[] = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (_, row) => (
        <Space>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: row.color || '#666',
              display: 'inline-block',
            }}
          />
          <span>{row.name}</span>
          {Number(row.is_system) === 1 ? <Tag>系统</Tag> : null}
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      render: (v) => v || '--',
    },
    {
      title: '账号数',
      dataIndex: 'account_count',
      width: 100,
      search: false,
    },
    {
      title: '颜色',
      dataIndex: 'color',
      width: 120,
      search: false,
      render: (v) => v || '--',
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, row) => [
        <Button
          key="edit"
          type="link"
          icon={<EditOutlined />}
          onClick={() => setEditing(row)}
        >
          编辑
        </Button>,
        <Popconfirm
          key="delete"
          title="确认删除该分组？"
          description="删除后该组账号会迁移到默认分组；系统分组不可删。"
          onConfirm={async () => {
            try {
              const res = await deleteGroup(row.id);
              if (res?.success === false) {
                message.error(
                  (typeof res.error === 'object' && res.error?.message) ||
                    res.message ||
                    '删除失败',
                );
                return;
              }
              message.success('删除成功');
              await reload();
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

  return (
    <PageContainer
      title="分组管理"
      subTitle="对接 /api/groups"
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void reload();
            }}
            loading={groupsQuery.isFetching}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建分组
          </Button>
        </Space>
      }
    >
      <ProTable<GroupItem>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        search={false}
        loading={groupsQuery.isLoading || groupsQuery.isFetching}
        dataSource={dataSource}
        pagination={{ pageSize: 20 }}
        options={false}
        toolBarRender={false}
      />

      <ModalForm
        title="新建分组"
        open={createOpen}
        modalProps={{ destroyOnHidden: true, onCancel: () => setCreateOpen(false) }}
        onOpenChange={setCreateOpen}
        initialValues={{ color: '#B85C38' }}
        onFinish={async (values) => {
          try {
            const res = await createGroup({
              name: values.name,
              description: values.description,
              color: values.color,
              proxy_url: values.proxy_url,
            });
            if (res?.success === false) {
              message.error(
                (typeof res.error === 'object' && res.error?.message) ||
                  res.message ||
                  '创建失败',
              );
              return false;
            }
            message.success('创建成功');
            await reload();
            return true;
          } catch (error: any) {
            message.error(error?.message || '创建失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="name"
          label="名称"
          rules={[{ required: true, message: '请输入分组名称' }]}
        />
        <ProFormTextArea name="description" label="描述" />
        <ProFormText name="color" label="颜色" placeholder="#B85C38" />
        <ProFormText name="proxy_url" label="代理 URL" />
      </ModalForm>

      <ModalForm
        title="编辑分组"
        open={!!editing}
        key={editing?.id || 'edit'}
        modalProps={{
          destroyOnHidden: true,
          onCancel: () => setEditing(null),
        }}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        initialValues={{
          name: editing?.name,
          description: editing?.description || '',
          color: editing?.color || '#B85C38',
          proxy_url: editing?.proxy_url || '',
        }}
        onFinish={async (values) => {
          if (!editing) return false;
          try {
            const res = await updateGroup(editing.id, {
              name: values.name,
              description: values.description,
              color: values.color,
              proxy_url: values.proxy_url,
            });
            if (res?.success === false) {
              message.error(
                (typeof res.error === 'object' && res.error?.message) ||
                  res.message ||
                  '更新失败',
              );
              return false;
            }
            message.success('更新成功');
            setEditing(null);
            await reload();
            return true;
          } catch (error: any) {
            message.error(error?.message || '更新失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="name"
          label="名称"
          rules={[{ required: true, message: '请输入分组名称' }]}
        />
        <ProFormTextArea name="description" label="描述" />
        <ProFormText name="color" label="颜色" />
        <ProFormText name="proxy_url" label="代理 URL" />
      </ModalForm>
    </PageContainer>
  );
};

export default GroupsPage;
