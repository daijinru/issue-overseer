import { useCallback, useEffect, useRef, useState } from 'react';
import { getIssue } from '../api/client';
import type { Issue } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export function useIssueDetail(issueId: string | null) {
  const [issue, setIssue] = useState<Issue | null>(null);
  const [loading, setLoading] = useState(false);
  const eventSource = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    if (!issueId) return;
    try {
      setIssue(await getIssue(issueId));
    } catch (error) {
      console.error('Failed to fetch issue detail:', error);
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  useEffect(() => {
    if (!issueId) {
      setIssue(null);
      return;
    }
    setLoading(true);
    void refresh();
  }, [issueId, refresh]);

  useEffect(() => {
    if (!issueId || issue?.status !== 'running') {
      eventSource.current?.close();
      eventSource.current = null;
      return;
    }

    const source = new EventSource(`${API_BASE}/api/issues/${issueId}/stream`);
    eventSource.current = source;
    source.addEventListener('task_end', () => {
      void refresh();
      source.close();
      eventSource.current = null;
    });
    source.onerror = () => {
      source.close();
      eventSource.current = null;
    };

    return () => {
      source.close();
      if (eventSource.current === source) eventSource.current = null;
    };
  }, [issue?.status, issueId, refresh]);

  return { issue, loading, refresh };
}
