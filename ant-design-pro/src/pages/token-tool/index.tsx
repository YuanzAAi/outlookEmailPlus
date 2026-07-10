import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Space } from 'antd';
import React from 'react';

const TokenToolPage: React.FC = () => (
  <PageContainer title="OAuth Token 工具" subTitle="迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="过渡方案"
      description="完整 SPA 化前可先打开后端既有 /token-tool 页面；后续再把 PKCE 流程迁入本页。"
    />
    <Space>
      <Button
        type="primary"
        onClick={() => {
          window.open(
            '/token-tool',
            'token-tool',
            'width=720,height=860,scrollbars=yes',
          );
        }}
      >
        打开旧版 Token 工具
      </Button>
    </Space>
  </PageContainer>
);

export default TokenToolPage;
