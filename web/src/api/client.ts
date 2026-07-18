import type {
  CCConnectProject,
  Execution,
  ExecutionLog,
  ExecutionStep,
  Issue,
  IssueCreateRequest,
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

export function getHealth() {
  return request<{ status: string; version: string }>('/api/health');
}

export function createIssue(data: IssueCreateRequest): Promise<Issue> {
  return request<Issue>('/api/issues', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getCCConnectProjects(): Promise<CCConnectProject[]> {
  const response = await request<{ projects: CCConnectProject[] }>('/api/cc-connect/projects');
  return response.projects;
}

export function listIssues(status?: IssueStatus): Promise<Issue[]> {
  const params = status ? `?status=${status}` : '';
  return request<Issue[]>(`/api/issues${params}`);
}

export function getIssue(id: string): Promise<Issue> {
  return request<Issue>(`/api/issues/${id}`);
}

export function runIssue(id: string) {
  return request<{ message: string; issue_id: string }>(`/api/issues/${id}/run`, { method: 'POST' });
}

export function cancelIssue(id: string) {
  return request<{ message: string; issue_id: string }>(`/api/issues/${id}/cancel`, { method: 'POST' });
}

export function deleteIssue(id: string) {
  return request<void>(`/api/issues/${id}`, { method: 'DELETE' });
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function retryIssue(id: string, data?: IssueRetryRequest) {
  return request<{ message: string; issue_id: string }>(`/api/issues/${id}/retry`, {
    method: 'POST',
    body: JSON.stringify(data ?? {}),
  });
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function getIssueLogs(id: string) {
  return request<ExecutionLog[]>(`/api/issues/${id}/logs`);
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function getIssueExecutions(id: string) {
  return request<Execution[]>(`/api/issues/${id}/executions`);
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function getIssueSteps(id: string) {
  return request<ExecutionStep[]>(`/api/issues/${id}/steps`);
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function updateSpec(id: string, spec: string) {
  return request<Issue>(`/api/issues/${id}/spec`, { method: 'PUT', body: JSON.stringify({ spec }) });
}

/** @deprecated The remaining callers are removed with the legacy detail UI in Task 5. */
export function rejectSpec(id: string) {
  return request<Issue>(`/api/issues/${id}/reject-spec`, { method: 'POST' });
}
