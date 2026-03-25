import { Collapse, Tag, Typography, Space, Empty } from 'antd';
import {
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  SettingOutlined,
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

  const isLifecycle = (exec: Execution) => exec.turn_number === 0 && exec.attempt_number === 0;

  const items = executions.map((exec) => ({
    key: exec.id,
    label: (
      <Space>
        {isLifecycle(exec) ? (
          <SettingOutlined style={{ color: '#8c8c8c' }} />
        ) : (
          getStatusIcon(exec.status)
        )}
        <span>
          {isLifecycle(exec)
            ? '任务生命周期'
            : `Turn ${exec.turn_number} / Attempt ${exec.attempt_number}`}
        </span>
        <ExecutionStatusTag status={exec.status} />
        <Tag>{formatDuration(exec.duration_ms)}</Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {new Date(exec.started_at).toLocaleString()}
        </Typography.Text>
      </Space>
    ),
    children: (
      <div>
        {isLifecycle(exec) && (
          <div style={{ marginBottom: 12 }}>
            <Typography.Text type="secondary">
              此记录为任务级生命周期日志（分支创建、Git 提交、PR 创建等），非 AI 执行轮次。详细日志请查看「执行日志」标签页。
            </Typography.Text>
          </div>
        )}
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
