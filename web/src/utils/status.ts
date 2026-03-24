import type { IssueStatus, ExecutionStatus } from '../types';

// Issue status → Ant Design Tag color
export const issueStatusColor: Record<IssueStatus, string> = {
  open: 'blue',
  planning: 'processing',
  planned: 'purple',
  running: 'processing',
  review: 'cyan',
  done: 'success',
  waiting_human: 'warning',
  cancelled: 'default',
};

// Issue status → Chinese label
export const issueStatusLabel: Record<IssueStatus, string> = {
  open: '待处理',
  planning: '生成方案中',
  planned: '方案就绪',
  running: '执行中',
  review: '待审查',
  done: '已完成',
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
