import { Typography, Tag } from 'antd';
import { WarningOutlined, StopOutlined } from '@ant-design/icons';
import { IssueStatusTag } from './StatusTag';
import { ActionButtons } from './ActionButtons';
import type { Issue, IssuePriority } from '../types';

interface IssueCardProps {
  issue: Issue;
  onClick: (issue: Issue) => void;
  onActionDone: () => void;
}

const priorityConfig: Record<IssuePriority, { color: string; label: string; borderColor: string }> = {
  high:   { color: 'red',     label: 'HIGH',   borderColor: '#ff4d4f' },
  medium: { color: 'orange',  label: 'MED',    borderColor: '#fa8c16' },
  low:    { color: 'default', label: 'LOW',    borderColor: '#d9d9d9' },
};

export function IssueCard({ issue, onClick, onActionDone }: IssueCardProps) {
  const priority = priorityConfig[issue.priority] ?? priorityConfig.medium;
  const isWaiting = issue.status === 'waiting_human';
  const isCancelled = issue.status === 'cancelled';
  const isRunning = issue.status === 'running' || issue.status === 'planning';

  return (
    <div
      className={`issue-card ${isRunning ? 'issue-card-running' : ''}`}
      style={{ borderLeftColor: priority.borderColor }}
      onClick={() => onClick(issue)}
    >
      {/* Title row */}
      <div className="issue-card-header">
        <Typography.Text
          strong
          ellipsis
          style={{ flex: 1, fontSize: 13 }}
        >
          {issue.title}
        </Typography.Text>
        {isWaiting && <WarningOutlined style={{ color: '#faad14', marginLeft: 4 }} />}
        {isCancelled && <StopOutlined style={{ color: '#8c8c8c', marginLeft: 4 }} />}
      </div>

      {/* Description preview */}
      {issue.description && (
        <Typography.Paragraph
          type="secondary"
          ellipsis={{ rows: 2 }}
          style={{ fontSize: 12, margin: '4px 0 8px', lineHeight: 1.4 }}
        >
          {issue.description}
        </Typography.Paragraph>
      )}

      {/* Footer: priority + status */}
      <div className="issue-card-footer">
        <Tag color={priority.color} style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
          {priority.label}
        </Tag>
        <IssueStatusTag status={issue.status} />
      </div>

      {/* Hover quick-action buttons */}
      <div
        className="issue-card-actions"
        onClick={(e) => e.stopPropagation()}
      >
        <ActionButtons
          issueId={issue.id}
          status={issue.status}
          onActionDone={onActionDone}
          compact
        />
      </div>
    </div>
  );
}
