import type {
  Issue,
  Execution,
  ExecutionLog,
  ExecutionStep,
  IssueCreateRequest,
  IssueEditRequest,
  IssueRetryRequest,
  IssueStatus,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// Health check
export function getHealth() {
  return request<{ status: string; version: string }>('/api/health');
}

// Issue CRUD
export function createIssue(data: IssueCreateRequest) {
  return request<Issue>('/api/issues', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function listIssues(status?: IssueStatus) {
  const params = status ? `?status=${status}` : '';
  return request<Issue[]>(`/api/issues${params}`);
}

export function getIssue(id: string) {
  return request<Issue>(`/api/issues/${id}`);
}

// Issue actions
export function runIssue(id: string) {
  return request<{ message: string; issue_id: string }>(
    `/api/issues/${id}/run`,
    { method: 'POST' },
  );
}

export function cancelIssue(id: string) {
  return request<{ message: string; issue_id: string }>(
    `/api/issues/${id}/cancel`,
    { method: 'POST' },
  );
}

export function retryIssue(id: string, data?: IssueRetryRequest) {
  return request<{ message: string; issue_id: string }>(
    `/api/issues/${id}/retry`,
    {
      method: 'POST',
      body: JSON.stringify(data ?? {}),
    },
  );
}

// Logs & executions
export function getIssueLogs(id: string) {
  return request<ExecutionLog[]>(`/api/issues/${id}/logs`);
}

export function getIssueExecutions(id: string) {
  return request<Execution[]>(`/api/issues/${id}/executions`);
}

export function getIssueSteps(id: string) {
  return request<ExecutionStep[]>(`/api/issues/${id}/steps`);
}

// Kanban actions
export function planIssue(id: string) {
  return request<{ message: string; issue_id: string }>(
    `/api/issues/${id}/plan`,
    { method: 'POST' },
  );
}

export function updateSpec(id: string, spec: string) {
  return request<Issue>(`/api/issues/${id}/spec`, {
    method: 'PUT',
    body: JSON.stringify({ spec }),
  });
}

export function rejectSpec(id: string) {
  return request<Issue>(`/api/issues/${id}/reject-spec`, {
    method: 'POST',
  });
}

export function completeIssue(id: string) {
  return request<Issue>(`/api/issues/${id}/complete`, {
    method: 'POST',
  });
}

// Issue edit & delete
export function editIssue(id: string, data: IssueEditRequest) {
  return request<Issue>(`/api/issues/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function deleteIssue(id: string) {
  return request<{ message: string }>(`/api/issues/${id}`, {
    method: 'DELETE',
  });
}
