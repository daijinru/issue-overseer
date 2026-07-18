import { Tag, Typography } from 'antd';
import { IssueStatusTag } from './StatusTag';
import { ActionButtons } from './ActionButtons';
import type { Issue } from '../types';

interface IssueCardProps {
  issue: Issue;
  onClick: (issue: Issue) => void;
  onActionDone: () => void;
}

export function IssueCard({ issue, onClick, onActionDone }: IssueCardProps) {
  const isRunning = issue.status === 'running';

  return (
    <div
      className={`issue-card ${isRunning ? 'issue-card-running' : ''}`}
      style={{ borderLeftColor: isRunning ? '#fa8c16' : '#1677ff' }}
      onClick={() => onClick(issue)}
    >
      <div className="issue-card-header">
        <Typography.Text strong ellipsis style={{ flex: 1, fontSize: 13 }}>
          {issue.content}
        </Typography.Text>
      </div>

      <Typography.Text type="secondary" ellipsis style={{ display: 'block', fontSize: 12, margin: '4px 0 8px' }}>
        {issue.project}
      </Typography.Text>

      <div className="issue-card-footer">
        {issue.status === 'finished' && issue.outcome && (
          <Tag color={issue.outcome === 'success' ? 'success' : 'error'}>
            {issue.outcome === 'success' ? '成功' : '失败'}
          </Tag>
        )}
        <IssueStatusTag status={issue.status} />
      </div>

      <div className="issue-card-actions" onClick={(event) => event.stopPropagation()}>
        <ActionButtons issueId={issue.id} status={issue.status} onActionDone={onActionDone} compact />
      </div>
    </div>
  );
}
