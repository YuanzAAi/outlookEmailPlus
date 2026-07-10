import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const PoolAdminPage: React.FC = () => (
  <PageContainer title="邮箱池管理" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api 邮箱池管理与 claim 状态。"
    />
    <Empty description="邮箱池管理骨架" />
  </PageContainer>
);

export default PoolAdminPage;
