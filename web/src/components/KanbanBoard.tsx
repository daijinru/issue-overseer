import { useMemo } from 'react';
import { KanbanColumn } from './KanbanColumn';
import { KANBAN_COLUMNS, groupIssuesByColumn } from '../utils/kanban';
import type { Issue } from '../types';

interface KanbanBoardProps {
  issues: Issue[];
  onCardClick: (issue: Issue) => void;
}

export function KanbanBoard({ issues, onCardClick }: KanbanBoardProps) {
  const grouped = useMemo(() => groupIssuesByColumn(issues), [issues]);

  return (
    <div className="kanban-board">
      {KANBAN_COLUMNS.map((col) => (
        <KanbanColumn
          key={col.key}
          column={col}
          issues={grouped[col.key] ?? []}
          onCardClick={onCardClick}
        />
      ))}
    </div>
  );
}
