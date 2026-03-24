// Issue statuses — mirrors backend IssueStatus enum
export type IssueStatus =
  | 'open'
  | 'planning'
  | 'planned'
  | 'running'
  | 'review'
  | 'done'
  | 'waiting_human'
  | 'cancelled';

// Issue priority — mirrors backend IssuePriority enum
export type IssuePriority = 'high' | 'medium' | 'low';

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
  failure_reason: string | null;
  workspace: string | null;
  pr_url: string | null;
  priority: IssuePriority;
  spec: string | null;
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

// Persisted execution step — mirrors backend ExecutionStep model
export interface ExecutionStep {
  id: number;
  execution_id: string;
  step_type: 'tool_use' | 'text' | 'step';
  tool: string | null;
  target: string | null;
  summary: string | null;
  created_at: string;
}

// Request types
export interface IssueCreateRequest {
  title: string;
  description?: string;
  workspace?: string;
  priority?: IssuePriority;
}

export interface IssueRetryRequest {
  human_instruction?: string;
  workspace?: string;
}

// Edit issue request
export interface IssueEditRequest {
  title?: string;
  description?: string;
  priority?: IssuePriority;
}

// SSE event types — mirrors backend EventBus event_type values
export type SSEEventType =
  | 'task_start'
  | 'task_end'
  | 'turn_start'
  | 'turn_end'
  | 'attempt_start'
  | 'attempt_end'
  | 'git_commit'
  | 'git_push'
  | 'pr_created'
  | 'task_cancelled'
  | 'plan_start'
  | 'plan_end'
  | 'opencode_step';

export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
}

// OpenCode streaming step — real-time AI operation visibility
export interface OpenCodeStep {
  step_type: 'tool_use' | 'text' | 'step';
  tool?: string;        // read, edit, bash, grep, glob, … (for step_type === 'tool_use')
  target?: string;      // file path or command (for step_type === 'tool_use')
  summary?: string;     // text summary (for step_type === 'text' or 'step')
  timestamp?: string;   // ISO 8601 from SSE event envelope
}
