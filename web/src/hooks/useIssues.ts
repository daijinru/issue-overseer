import { useState, useEffect, useCallback } from 'react';
import { listIssues } from '../api/client';
import { usePolling } from './usePolling';
import type { Issue } from '../types';

export function useIssues() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchIssues = useCallback(async () => {
    try {
      const data = await listIssues();
      setIssues(data);
    } catch (err) {
      console.error('Failed to fetch issues:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    setLoading(true);
    fetchIssues();
  }, [fetchIssues]);

  // Poll every 5s if any issue is running or planning
  const hasActive = issues.some(
    (i) => i.status === 'running' || i.status === 'planning',
  );
  usePolling(fetchIssues, 5000, hasActive);

  return {
    issues,
    loading,
    refresh: fetchIssues,
  };
}
