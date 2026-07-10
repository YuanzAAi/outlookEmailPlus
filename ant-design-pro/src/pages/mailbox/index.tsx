import { PageContainer } from '@ant-design/pro-components';
import { Alert, Empty } from 'antd';
import React from 'react';

const MailboxPage: React.FC = () => (
  <PageContainer title="邮箱" subTitle="邮件阅读 · 迁移中">
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="待迁移"
      description="将对接分组 / 账号列表与 /api/emails/* 邮件读写链路。"
    />
    <Empty description="邮箱工作区骨架" />
  </PageContainer>
);

export default MailboxPage;
