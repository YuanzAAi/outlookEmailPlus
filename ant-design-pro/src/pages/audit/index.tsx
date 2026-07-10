import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const AuditPage: React.FC = () => (
  <PageContainer title="审计日志" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api/audit 查询接口。"
    />
    <Empty description="审计日志骨架" />
  </PageContainer>
);

export default AuditPage;
