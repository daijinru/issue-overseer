import { useState, useEffect, useCallback } from 'react';
import { getIssue, getIssueExecutions, getIssueLogs } from '../api/client';
import { usePolling } from './usePolling';
import type { Issue, Execution, ExecutionLog } from '../types';

export function useIssueDetail(issueId: string | null) {
  const [issue, setIssue] = useState<Issue | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchDetail = useCallback(async () => {
    if (!issueId) return;
    try {
      const [issueData, execData, logData] = await Promise.all([
        getIssue(issueId),
        getIssueExecutions(issueId),
        getIssueLogs(issueId),
      ]);
      setIssue(issueData);
      setExecutions(execData);
      setLogs(logData);
    } catch (err) {
      console.error('Failed to fetch issue detail:', err);
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  // Fetch when issueId changes
  useEffect(() => {
    if (issueId) {
      setLoading(true);
      fetchDetail();
    } else {
      setIssue(null);
      setExecutions([]);
      setLogs([]);
    }
  }, [issueId, fetchDetail]);

  // Poll every 3s if issue is running
  const isRunning = issue?.status === 'running';
  usePolling(fetchDetail, 3000, isRunning);

  return {
    issue,
    executions,
    logs,
    loading,
    refresh: fetchDetail,
  };
}
