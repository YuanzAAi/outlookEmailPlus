import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const TempEmailsPage: React.FC = () => (
  <PageContainer title="临时邮箱" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接临时邮箱 Provider 与 /api/temp-emails/*。"
    />
    <Empty description="临时邮箱骨架" />
  </PageContainer>
);

export default TempEmailsPage;
