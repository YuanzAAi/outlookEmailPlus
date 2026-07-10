import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const GroupsPage: React.FC = () => (
  <PageContainer title="分组管理" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api/groups 的 CRUD 与账号归属。"
    />
    <Empty description="分组管理骨架" />
  </PageContainer>
);

export default GroupsPage;
