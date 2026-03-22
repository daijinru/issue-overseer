import { useState, useEffect, useCallback } from 'react';
import { listIssues } from '../api/client';
import { usePolling } from './usePolling';
import type { Issue, IssueStatus } from '../types';

export function useIssues() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<IssueStatus | 'all'>('all');

  const fetchIssues = useCallback(async () => {
    try {
      const filter = statusFilter === 'all' ? undefined : statusFilter;
      const data = await listIssues(filter);
      setIssues(data);
    } catch (err) {
      console.error('Failed to fetch issues:', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  // Initial fetch + when filter changes
  useEffect(() => {
    setLoading(true);
    fetchIssues();
  }, [fetchIssues]);

  // Poll every 5s if any issue is running
  const hasRunning = issues.some((i) => i.status === 'running');
  usePolling(fetchIssues, 5000, hasRunning);

  return {
    issues,
    loading,
    statusFilter,
    setStatusFilter,
    refresh: fetchIssues,
  };
}
