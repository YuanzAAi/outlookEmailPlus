import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const AccountsPage: React.FC = () => (
  <PageContainer title="账号管理" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api/accounts 的列表、导入、编辑、Token 校验等。"
    />
    <Empty description="账号管理骨架" />
  </PageContainer>
);

export default AccountsPage;
