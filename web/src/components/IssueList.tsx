import { useState } from 'react';
import { Button, List, Segmented, Typography, Space } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { IssueStatusTag } from './StatusTag';
import { IssueForm } from './IssueForm';
import type { Issue, IssueStatus } from '../types';

const STATUS_OPTIONS: Array<{ label: string; value: IssueStatus | 'all' }> = [
  { label: '全部', value: 'all' },
  { label: '待处理', value: 'open' },
  { label: '执行中', value: 'running' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'failed' },
  { label: '等待指令', value: 'waiting_human' },
];

interface IssueListProps {
  issues: Issue[];
  loading: boolean;
  selectedId: string | null;
  statusFilter: IssueStatus | 'all';
  onSelect: (id: string) => void;
  onStatusFilterChange: (status: IssueStatus | 'all') => void;
  onRefresh: () => void;
  onCreated: () => void;
}

export function IssueList({
  issues,
  loading,
  selectedId,
  statusFilter,
  onSelect,
  onStatusFilterChange,
  onRefresh,
  onCreated,
}: IssueListProps) {
  const [formOpen, setFormOpen] = useState(false);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '16px 16px 8px', borderBottom: '1px solid #f0f0f0' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Issues
          </Typography.Title>
          <Space>
            <Button
              icon={<ReloadOutlined />}
              size="small"
              onClick={onRefresh}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              size="small"
              onClick={() => setFormOpen(true)}
            >
              新建
            </Button>
          </Space>
        </Space>
        <Segmented
          block
          size="small"
          options={STATUS_OPTIONS}
          value={statusFilter}
          onChange={(val) => onStatusFilterChange(val as IssueStatus | 'all')}
        />
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
        <List
          loading={loading}
          dataSource={issues}
          locale={{ emptyText: '暂无 Issue' }}
          renderItem={(issue) => (
            <List.Item
              key={issue.id}
              onClick={() => onSelect(issue.id)}
              style={{
                cursor: 'pointer',
                padding: '8px 12px',
                borderRadius: 6,
                background: issue.id === selectedId ? '#e6f4ff' : undefined,
                marginTop: 4,
              }}
            >
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography.Text strong ellipsis style={{ flex: 1 }}>
                    {issue.title}
                  </Typography.Text>
                  <IssueStatusTag status={issue.status} />
                </div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {new Date(issue.created_at).toLocaleString()}
                </Typography.Text>
              </div>
            </List.Item>
          )}
        />
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
