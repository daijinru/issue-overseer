import type { IssueStatus, ExecutionStatus } from '../types';

// Issue status → Ant Design Tag color
export const issueStatusColor: Record<IssueStatus, string> = {
  open: 'blue',
  running: 'processing',
  done: 'success',
  failed: 'error',
  waiting_human: 'warning',
  cancelled: 'default',
};

// Issue status → Chinese label
export const issueStatusLabel: Record<IssueStatus, string> = {
  open: '待处理',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  waiting_human: '等待指令',
  cancelled: '已取消',
};

// Execution status → Ant Design Tag color
export const executionStatusColor: Record<ExecutionStatus, string> = {
  running: 'processing',
  completed: 'success',
  failed: 'error',
  cancelled: 'default',
  timeout: 'warning',
};

// Execution status → Chinese label
export const executionStatusLabel: Record<ExecutionStatus, string> = {
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  timeout: '超时',
};
