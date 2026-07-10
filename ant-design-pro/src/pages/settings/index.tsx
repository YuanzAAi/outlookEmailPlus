import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const SettingsPage: React.FC = () => (
  <PageContainer title="系统设置" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api/settings 与通知 / AI / 外部 API 等配置。"
    />
    <Empty description="系统设置骨架" />
  </PageContainer>
);

export default SettingsPage;
