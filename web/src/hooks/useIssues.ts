import { useState, useEffect, useCallback } from 'react';
import { listIssues } from '../api/client';
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

  return {
    issues,
    loading,
    refresh: fetchIssues,
  };
}
