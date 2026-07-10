import { PageContainer, ProCard, StatisticCard } from '@ant-design/pro-components';
import { Alert, Col, Row, Typography } from 'antd';
import React from 'react';

/**
 * 概览页骨架 —— P1 将对接 /api/overview/*
 */
const OverviewPage: React.FC = () => {
  return (
    <PageContainer
      title="概览"
      subTitle="Dashboard · 迁移中"
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="前端迁移进行中"
        description="本页为 Ant Design Pro 骨架。下一阶段将对接 /api/overview/summary 等接口，替换旧 templates/index.html 的 dashboard。"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard statistic={{ title: '账号', value: '—', description: '待对接' }} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard statistic={{ title: '分组', value: '—', description: '待对接' }} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard statistic={{ title: '临时邮箱', value: '—', description: '待对接' }} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <StatisticCard statistic={{ title: '邮箱池', value: '—', description: '待对接' }} />
        </Col>
      </Row>
      <ProCard title="迁移说明" style={{ marginTop: 16 }} bordered>
        <Typography.Paragraph>
          旧前端功能模块对应关系：
        </Typography.Paragraph>
        <Typography.Paragraph>
          <ul>
            <li>dashboard → /overview</li>
            <li>mailbox → /mailbox</li>
            <li>pool-admin → /pool-admin</li>
            <li>temp-emails → /temp-emails</li>
            <li>settings / audit / refresh-log → 对应路由</li>
          </ul>
        </Typography.Paragraph>
      </ProCard>
    </PageContainer>
  );
};

export default OverviewPage;
