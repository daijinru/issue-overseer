import type { Issue, IssueStatus } from '../types';

export interface KanbanColumnDef {
  key: string;
  title: string;
  agentRole: string;
  statuses: IssueStatus[];
  color: string;
}

export const KANBAN_COLUMNS: KanbanColumnDef[] = [
  { key: 'backlog',  title: 'Backlog',  agentRole: 'Refiner',      statuses: ['open'],                color: '#1677ff' },
  { key: 'todo',     title: 'Todo',     agentRole: 'Orchestrator', statuses: ['planning', 'planned'], color: '#722ed1' },
  { key: 'dev',      title: 'Dev',      agentRole: 'Crafter',      statuses: ['running'],             color: '#fa8c16' },
  { key: 'review',   title: 'Review',   agentRole: 'Guard',        statuses: ['review'],              color: '#13c2c2' },
  { key: 'done',     title: 'Done',     agentRole: 'Reporter',     statuses: ['done'],                color: '#52c41a' },
];

/** Map status to its primary column key */
const statusToColumn: Record<string, string> = {};
for (const col of KANBAN_COLUMNS) {
  for (const s of col.statuses) {
    statusToColumn[s] = col.key;
  }
}

/**
 * Determine which kanban column an issue belongs to.
 * waiting_human / cancelled are overlay states — card stays in the column
 * where it was before failing/cancelling, inferred from pr_url/branch_name/spec.
 */
export function getColumnForIssue(issue: Issue): string {
  if (issue.status === 'waiting_human' || issue.status === 'cancelled') {
    if (issue.pr_url) return 'review';
    if (issue.branch_name) return 'dev';
    if (issue.spec) return 'todo';
    return 'backlog';
  }
  return statusToColumn[issue.status] ?? 'backlog';
}

/** Priority sort weight: high=0, medium=1, low=2 */
const priorityWeight: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/**
 * Sort issues within a column: by priority (high first) then by updated_at (newest first).
 */
export function sortColumnIssues(issues: Issue[]): Issue[] {
  return [...issues].sort((a, b) => {
    const pa = priorityWeight[a.priority] ?? 1;
    const pb = priorityWeight[b.priority] ?? 1;
    if (pa !== pb) return pa - pb;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
}

/**
 * Group issues into kanban columns. Returns a map of column key → sorted issues.
 */
export function groupIssuesByColumn(issues: Issue[]): Record<string, Issue[]> {
  const groups: Record<string, Issue[]> = {};
  for (const col of KANBAN_COLUMNS) {
    groups[col.key] = [];
  }
  for (const issue of issues) {
    const colKey = getColumnForIssue(issue);
    if (groups[colKey]) {
      groups[colKey].push(issue);
    }
  }
  // Sort each column
  for (const key of Object.keys(groups)) {
    groups[key] = sortColumnIssues(groups[key]);
  }
  return groups;
}
