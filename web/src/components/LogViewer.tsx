import { Empty, Typography } from 'antd';
import type { ExecutionLog, LogLevel } from '../types';

interface LogViewerProps {
  logs: ExecutionLog[];
}

const LOG_COLORS: Record<LogLevel, string> = {
  info: '#1677ff',
  warn: '#faad14',
  error: '#ff4d4f',
};

const LOG_BG: Record<LogLevel, string> = {
  info: 'transparent',
  warn: '#fffbe6',
  error: '#fff2f0',
};

export function LogViewer({ logs }: LogViewerProps) {
  if (logs.length === 0) {
    return <Empty description="暂无执行日志" />;
  }

  return (
    <div
      style={{
        fontFamily: 'monospace',
        fontSize: 13,
        lineHeight: 1.8,
      }}
    >
      {logs.map((log) => (
        <div
          key={log.id}
          style={{
            padding: '2px 8px',
            borderRadius: 2,
            background: LOG_BG[log.level],
          }}
        >
          <Typography.Text type="secondary" style={{ fontSize: 11, marginRight: 8 }}>
            {new Date(log.created_at).toLocaleTimeString()}
          </Typography.Text>
          <Typography.Text
            style={{
              color: LOG_COLORS[log.level],
              fontWeight: log.level === 'error' ? 600 : 400,
              marginRight: 8,
              textTransform: 'uppercase',
              fontSize: 11,
              minWidth: 40,
              display: 'inline-block',
            }}
          >
            [{log.level}]
          </Typography.Text>
          <span>{log.message}</span>
        </div>
      ))}
    </div>
  );
}
