import type { Issue, IssueStatus } from '../types';

export interface KanbanColumnDef {
  key: 'todo' | 'dev' | 'done';
  title: string;
  agentRole: string;
  statuses: IssueStatus[];
  color: string;
}

export const KANBAN_COLUMNS: KanbanColumnDef[] = [
  { key: 'todo', title: 'Queued', agentRole: 'cc-connect', statuses: ['pending'], color: '#722ed1' },
  { key: 'dev', title: 'Running', agentRole: 'cc-connect', statuses: ['running'], color: '#fa8c16' },
  { key: 'done', title: 'Done', agentRole: 'cc-connect', statuses: ['finished'], color: '#52c41a' },
];

const statusToColumn: Record<IssueStatus, KanbanColumnDef['key']> = {
  pending: 'todo',
  running: 'dev',
  finished: 'done',
};

export function getColumnForIssue(issue: Issue): KanbanColumnDef['key'] {
  return statusToColumn[issue.status];
}

export function sortColumnIssues(issues: Issue[]): Issue[] {
  return [...issues].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );
}

export function groupIssuesByColumn(issues: Issue[]): Record<KanbanColumnDef['key'], Issue[]> {
  const groups: Record<KanbanColumnDef['key'], Issue[]> = { todo: [], dev: [], done: [] };
  for (const issue of issues) {
    groups[getColumnForIssue(issue)].push(issue);
  }
  for (const key of Object.keys(groups) as KanbanColumnDef['key'][]) {
    groups[key] = sortColumnIssues(groups[key]);
  }
  return groups;
}
