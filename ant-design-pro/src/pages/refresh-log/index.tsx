import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const RefreshLogPage: React.FC = () => (
  <PageContainer title="刷新日志" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 Token 刷新与调度日志接口。"
    />
    <Empty description="刷新日志骨架" />
  </PageContainer>
);

export default RefreshLogPage;
