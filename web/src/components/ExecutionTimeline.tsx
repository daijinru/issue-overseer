import { Collapse, Tag, Typography, Space, Empty } from 'antd';
import {
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import { ExecutionStatusTag } from './StatusTag';
import type { Execution } from '../types';

interface ExecutionTimelineProps {
  executions: Execution[];
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed':
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    case 'timeout':
      return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
    case 'running':
      return <ClockCircleOutlined style={{ color: '#1677ff' }} spin />;
    default:
      return <ClockCircleOutlined />;
  }
}

export function ExecutionTimeline({ executions }: ExecutionTimelineProps) {
  if (executions.length === 0) {
    return <Empty description="暂无执行记录" />;
  }

  const items = executions.map((exec) => ({
    key: exec.id,
    label: (
      <Space>
        {getStatusIcon(exec.status)}
        <span>Turn {exec.turn_number} / Attempt {exec.attempt_number}</span>
        <ExecutionStatusTag status={exec.status} />
        <Tag>{formatDuration(exec.duration_ms)}</Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {new Date(exec.started_at).toLocaleString()}
        </Typography.Text>
      </Space>
    ),
    children: (
      <div>
        {exec.error_message && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text type="danger" strong>
              错误信息:
            </Typography.Text>
            <pre
              style={{
                background: '#fff2f0',
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 200,
                overflow: 'auto',
              }}
            >
              {exec.error_message}
            </pre>
          </div>
        )}
        {exec.result && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>执行结果:</Typography.Text>
            <pre
              style={{
                background: '#f6ffed',
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 300,
                overflow: 'auto',
              }}
            >
              {exec.result}
            </pre>
          </div>
        )}
        {exec.context_snapshot && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text strong>上下文快照:</Typography.Text>
            <pre
              style={{
                background: '#f0f5ff',
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 200,
                overflow: 'auto',
              }}
            >
              {(() => {
                try {
                  return JSON.stringify(JSON.parse(exec.context_snapshot), null, 2);
                } catch {
                  return exec.context_snapshot;
                }
              })()}
            </pre>
          </div>
        )}
        {exec.git_diff_snapshot && (
          <div>
            <Typography.Text strong>Git Diff:</Typography.Text>
            <pre
              style={{
                background: '#fffbe6',
                padding: 8,
                borderRadius: 4,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 200,
                overflow: 'auto',
              }}
            >
              {exec.git_diff_snapshot}
            </pre>
          </div>
        )}
      </div>
    ),
  }));

  return <Collapse items={items} size="small" />;
}
