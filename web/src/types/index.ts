export type IssueStatus = 'pending' | 'running' | 'finished';

export type IssueOutcome = 'success' | 'error';

export interface Issue {
  id: string;
  content: string;
  project: string;
  status: IssueStatus;
  outcome: IssueOutcome | null;
  result: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface IssueCreateRequest {
  content: string;
  project: string;
}

export interface CCConnectProject {
  name: string;
}
