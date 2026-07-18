import type { IssueStatus } from '../types';

// Issue status → Ant Design Tag color
export const issueStatusColor: Record<IssueStatus, string> = {
  pending: 'blue',
  running: 'processing',
  finished: 'success',
};

// Issue status → Chinese label
export const issueStatusLabel: Record<IssueStatus, string> = {
  pending: '待执行',
  running: '执行中',
  finished: '已结束',
};
