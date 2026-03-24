import { useState } from 'react';
import { Button, Badge, Space, Typography } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { IssueForm } from './IssueForm';
import type { Issue } from '../types';

interface TopBarProps {
  issues: Issue[];
  onCreated: () => void;
  onRefresh: () => void;
}

export function TopBar({ issues, onCreated, onRefresh }: TopBarProps) {
  const [formOpen, setFormOpen] = useState(false);

  const runningCount = issues.filter(
    (i) => i.status === 'running' || i.status === 'planning',
  ).length;

  const queuedCount = issues.filter(
    (i) => i.status === 'open' || i.status === 'planned',
  ).length;

  return (
    <div className="topbar">
      <div className="topbar-left">
        <Typography.Title level={4} style={{ margin: 0 }}>
          <span style={{ marginRight: 8 }}>🥭</span>
          Mango
        </Typography.Title>
      </div>
      <div className="topbar-right">
        <Space size="middle">
          <Badge count={runningCount} showZero={false} size="small" offset={[-4, 4]}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              Running: {runningCount}
            </Typography.Text>
          </Badge>
          <Badge count={queuedCount} showZero={false} size="small" color="#722ed1" offset={[-4, 4]}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              Queued: {queuedCount}
            </Typography.Text>
          </Badge>
          <Button
            icon={<ReloadOutlined />}
            size="small"
            onClick={onRefresh}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setFormOpen(true)}
          >
            新建 Issue
          </Button>
        </Space>
      </div>

      <IssueForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onCreated={() => {
          setFormOpen(false);
          onCreated();
        }}
      />
    </div>
  );
}
