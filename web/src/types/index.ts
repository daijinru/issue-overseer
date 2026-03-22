// Issue statuses — mirrors backend IssueStatus enum
export type IssueStatus =
  | 'open'
  | 'running'
  | 'done'
  | 'failed'
  | 'waiting_human'
  | 'cancelled';

// Execution statuses — mirrors backend ExecutionStatus enum
export type ExecutionStatus =
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timeout';

// Log levels
export type LogLevel = 'info' | 'warn' | 'error';

// Issue entity
export interface Issue {
  id: string;
  title: string;
  description: string;
  status: IssueStatus;
  branch_name: string | null;
  human_instruction: string | null;
  workspace: string | null;
  created_at: string;
  updated_at: string;
}

// Execution entity
export interface Execution {
  id: string;
  issue_id: string;
  turn_number: number;
  attempt_number: number;
  status: ExecutionStatus;
  prompt: string | null;
  result: string | null;
  error_message: string | null;
  context_snapshot: string | null;
  git_diff_snapshot: string | null;
  duration_ms: number | null;
  started_at: string;
  finished_at: string | null;
}

// Execution log entry
export interface ExecutionLog {
  id: number;
  execution_id: string;
  level: LogLevel;
  message: string;
  created_at: string;
}

// Request types
export interface IssueCreateRequest {
  title: string;
  description?: string;
  workspace?: string;
}

export interface IssueRetryRequest {
  human_instruction?: string;
}
