import { useState, useEffect, useCallback, useRef } from 'react';
import { getIssue, getIssueExecutions, getIssueLogs, getIssueSteps } from '../api/client';
import { usePolling } from './usePolling';
import type { Issue, Execution, ExecutionLog, ExecutionStep, SSEEventType, OpenCodeStep } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

/** Terminal SSE events that signal the stream should close. */
const TERMINAL_EVENTS: SSEEventType[] = ['task_end', 'task_cancelled'];

/** SSE event types that trigger a full data refresh. */
const REFRESH_EVENTS: SSEEventType[] = [
  'task_start', 'task_end',
  'turn_start', 'turn_end',
  'attempt_start', 'attempt_end',
  'git_commit', 'git_push', 'pr_created',
  'task_cancelled',
];

/** All SSE event types we listen to — refresh events + streaming events. */
const ALL_SSE_EVENTS: SSEEventType[] = [...REFRESH_EVENTS, 'opencode_step', 'execution_log'];

/**
 * Convert persisted ExecutionStep[] to the OpenCodeStep[] format used by the UI.
 */
function toOpenCodeSteps(persisted: ExecutionStep[]): OpenCodeStep[] {
  return persisted.map((s) => ({
    step_type: s.step_type,
    tool: s.tool ?? undefined,
    target: s.target ?? undefined,
    summary: s.summary ?? undefined,
    timestamp: s.created_at,
  }));
}

export function useIssueDetail(issueId: string | null) {
  const [issue, setIssue] = useState<Issue | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [steps, setSteps] = useState<OpenCodeStep[]>([]);
  const [loading, setLoading] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);

  // Keep a ref to the EventSource so we can close it from anywhere.
  const esRef = useRef<EventSource | null>(null);

  // Track the count of persisted steps so SSE can append without duplicates.
  // When REST returns N persisted steps, SSE events only append on top of that baseline.
  const persistedStepCountRef = useRef<number>(0);

  const fetchDetail = useCallback(async () => {
    if (!issueId) return;
    try {
      const [issueData, execData, logData, stepData] = await Promise.all([
        getIssue(issueId),
        getIssueExecutions(issueId),
        getIssueLogs(issueId),
        getIssueSteps(issueId),
      ]);
      setIssue(issueData);
      setExecutions(execData);
      setLogs(logData);

      // Always load persisted steps as a baseline — regardless of status.
      //
      // For running issues: REST provides the backfill (steps before page load
      // or SSE reconnect), SSE appends new steps on top. The persistedStepCountRef
      // prevents duplicates when both REST and SSE deliver the same step.
      //
      // For completed issues: REST is the only source (SSE is closed).
      const historicalSteps = toOpenCodeSteps(stepData);
      persistedStepCountRef.current = historicalSteps.length;

      setSteps((prev) => {
        if (issueData.status !== 'running') {
          // Not running — REST is the single source of truth.
          return historicalSteps;
        }
        // Running — merge: REST backfill + any SSE-only steps that arrived
        // after the DB snapshot. SSE steps that were already persisted are
        // covered by historicalSteps; only keep SSE-appended steps beyond
        // the persisted count.
        const sseOnlyTail = prev.slice(persistedStepCountRef.current);
        return [...historicalSteps, ...sseOnlyTail];
      });
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
      persistedStepCountRef.current = 0;
      fetchDetail();
    } else {
      setIssue(null);
      setExecutions([]);
      setLogs([]);
      setSteps([]);
      persistedStepCountRef.current = 0;
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

    // Register a handler per event type.
    for (const eventType of ALL_SSE_EVENTS) {
      es.addEventListener(eventType, (evt) => {
        if (eventType === 'opencode_step') {
          // Append new step from SSE. Each step is also being persisted to DB
          // by the backend, so the next fetchDetail() will include it in the
          // REST baseline. We append here for immediate visibility.
          try {
            const stepData = JSON.parse((evt as MessageEvent).data) as OpenCodeStep;
            setSteps((prev) => [...prev, stepData]);
          } catch {
            // Ignore parse errors
          }
          return;
        }

        if (eventType === 'execution_log') {
          // Append new log entry from SSE for real-time visibility.
          // Uses a negative auto-decrement id to avoid collisions with DB ids.
          try {
            const data = JSON.parse((evt as MessageEvent).data) as {
              execution_id: string;
              level: string;
              message: string;
            };
            const newLog: ExecutionLog = {
              id: -(Date.now() + Math.random()),
              execution_id: data.execution_id,
              level: data.level as ExecutionLog['level'],
              message: data.message,
              created_at: new Date().toISOString(),
            };
            setLogs((prev) => [...prev, newLog]);
          } catch {
            // Ignore parse errors
          }
          return;
        }

        // Clear steps on new task start
        if (eventType === 'task_start') {
          setSteps([]);
          persistedStepCountRef.current = 0;
        }

        // All other events trigger a full data refresh.
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
    steps,
    loading,
    sseConnected,
    refresh: fetchDetail,
  };
}
