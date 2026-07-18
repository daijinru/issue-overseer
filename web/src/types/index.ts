export type IssueStatus = 'pending' | 'running' | 'finished';

/** @deprecated Temporary compatibility for the detail surface pending Task 5. */
export type LegacyIssueStatus =
  | 'open'
  | 'planning'
  | 'planned'
  | 'review'
  | 'done'
  | 'waiting_human'
  | 'cancelled';

export type AnyIssueStatus = IssueStatus | LegacyIssueStatus;

export type IssueOutcome = 'success' | 'error';

export interface Issue {
  id: string;
  content: string;
  project: string;
  status: AnyIssueStatus;
  outcome: IssueOutcome | null;
  result: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  title: string;
  /** @deprecated Legacy detail field pending Task 5. */
  description: string;
  /** @deprecated Legacy detail field pending Task 5. */
  priority: IssuePriority;
  /** @deprecated Legacy detail field pending Task 5. */
  workspace: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  branch_name: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  pr_url: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  spec: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  failure_reason: string | null;
  /** @deprecated Legacy detail field pending Task 5. */
  human_instruction: string | null;
}

export interface IssueCreateRequest {
  content: string;
  project: string;
}

export type IssuePriority = 'high' | 'medium' | 'low';

export interface IssueRetryRequest {
  human_instruction?: string;
  workspace?: string;
}

export interface IssueEditRequest {
  title?: string;
  description?: string;
  priority?: IssuePriority;
}

export interface CCConnectProject {
  name: string;
}

// Retained only while the unused legacy detail components are removed in Task 5.
export type ExecutionStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout';
export type LogLevel = 'info' | 'warn' | 'error';

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

export interface ExecutionLog {
  id: number;
  execution_id: string;
  level: LogLevel;
  message: string;
  created_at: string;
}

export interface ExecutionStep {
  id: number;
  execution_id: string;
  step_type: 'tool_use' | 'text' | 'step';
  tool: string | null;
  target: string | null;
  summary: string | null;
  created_at: string | null;
}

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
  | 'agent_step'
  | 'execution_log';

export interface OpenCodeStep {
  step_type: 'tool_use' | 'text' | 'step';
  tool?: string;
  target?: string;
  summary?: string;
  timestamp?: string | null;
}
