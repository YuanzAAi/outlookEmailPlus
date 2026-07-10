import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const PluginsPage: React.FC = () => (
  <PageContainer title="插件管理" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接 /api/plugins 安装、配置、连接测试。"
    />
    <Empty description="插件管理骨架" />
  </PageContainer>
);

export default PluginsPage;
