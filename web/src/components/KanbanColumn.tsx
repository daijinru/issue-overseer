import { Typography, Badge } from 'antd';
import { IssueCard } from './IssueCard';
import type { Issue } from '../types';
import type { KanbanColumnDef } from '../utils/kanban';

interface KanbanColumnProps {
  column: KanbanColumnDef;
  issues: Issue[];
  onCardClick: (issue: Issue) => void;
}

export function KanbanColumn({ column, issues, onCardClick }: KanbanColumnProps) {
  return (
    <div className="kanban-column">
      <div className="kanban-column-header" style={{ borderTopColor: column.color }}>
        <div className="kanban-column-title">
          <Typography.Text strong style={{ fontSize: 14 }}>
            {column.title}
          </Typography.Text>
          <Badge
            count={issues.length}
            showZero
            style={{ backgroundColor: column.color }}
            size="small"
          />
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          {column.agentRole}
        </Typography.Text>
      </div>
      <div className="kanban-column-body">
        {issues.map((issue) => (
          <IssueCard
            key={issue.id}
            issue={issue}
            onClick={onCardClick}
          />
        ))}
      </div>
    </div>
  );
}
