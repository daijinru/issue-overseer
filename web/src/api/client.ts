import type {
  CCConnectProject,
  Issue,
  IssueCreateRequest,
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
