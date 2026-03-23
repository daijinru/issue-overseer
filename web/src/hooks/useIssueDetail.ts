import { useState, useEffect, useCallback, useRef } from 'react';
import { getIssue, getIssueExecutions, getIssueLogs } from '../api/client';
import { usePolling } from './usePolling';
import type { Issue, Execution, ExecutionLog, SSEEventType } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

/** Terminal SSE events that signal the stream should close. */
const TERMINAL_EVENTS: SSEEventType[] = ['task_end', 'task_cancelled'];

/** All SSE event types we care about — each triggers a data refresh. */
const SSE_EVENTS: SSEEventType[] = [
  'task_start', 'task_end',
  'turn_start', 'turn_end',
  'attempt_start', 'attempt_end',
  'git_commit', 'git_push', 'pr_created',
  'task_cancelled',
];

export function useIssueDetail(issueId: string | null) {
  const [issue, setIssue] = useState<Issue | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);

  // Keep a ref to the EventSource so we can close it from anywhere.
  const esRef = useRef<EventSource | null>(null);

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

  // ── SSE connection management ────────────────────────────────
  const isRunning = issue?.status === 'running';

  useEffect(() => {
    if (!issueId || !isRunning) {
      // Close existing SSE if issue is no longer running.
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
        setSseConnected(false);
      }
      return;
    }

    const url = `${API_BASE}/api/issues/${issueId}/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setSseConnected(true);
    };

    // Register a handler per event type.  On every meaningful event we
    // simply re-fetch the full detail — cheap, reliable, no state-merging
    // complexity.
    for (const eventType of SSE_EVENTS) {
      es.addEventListener(eventType, () => {
        fetchDetail();

        // Terminal event → close the stream; the final fetchDetail() above
        // already captures the finished state.
        if ((TERMINAL_EVENTS as string[]).includes(eventType)) {
          es.close();
          esRef.current = null;
          setSseConnected(false);
        }
      });
    }

    es.onerror = () => {
      // Connection lost or failed to establish — fall back to polling.
      es.close();
      esRef.current = null;
      setSseConnected(false);
    };

    return () => {
      es.close();
      esRef.current = null;
      setSseConnected(false);
    };
  }, [issueId, isRunning, fetchDetail]);

  // ── Polling fallback ─────────────────────────────────────────
  // Only active when the issue is running AND SSE is not connected.
  usePolling(fetchDetail, 3000, isRunning && !sseConnected);

  return {
    issue,
    executions,
    logs,
    loading,
    sseConnected,
    refresh: fetchDetail,
  };
}
