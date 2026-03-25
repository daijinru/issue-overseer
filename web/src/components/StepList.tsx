import { useEffect, useRef } from 'react';
import { Empty, Spin, Typography } from 'antd';
import {
  ReadOutlined,
  EditOutlined,
  SearchOutlined,
  CodeOutlined,
  ThunderboltOutlined,
  MessageOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import type { OpenCodeStep } from '../types';

interface StepListProps {
  steps: OpenCodeStep[];
  isRunning: boolean;
}

/** Map tool name → icon + Chinese label. */
const TOOL_META: Record<string, { icon: React.ReactNode; label: string }> = {
  read: { icon: <ReadOutlined style={{ color: '#1677ff' }} />, label: '读取' },
  edit: { icon: <EditOutlined style={{ color: '#52c41a' }} />, label: '修改' },
  write: { icon: <EditOutlined style={{ color: '#52c41a' }} />, label: '写入' },
  shell: { icon: <ThunderboltOutlined style={{ color: '#fa8c16' }} />, label: '执行' },
  bash: { icon: <ThunderboltOutlined style={{ color: '#fa8c16' }} />, label: '执行' },
  grep: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '搜索' },
  glob: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '查找' },
  search: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '搜索' },
  codesearch: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '代码搜索' },
  websearch: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '网页搜索' },
  list: { icon: <SearchOutlined style={{ color: '#722ed1' }} />, label: '列目录' },
  task: { icon: <RocketOutlined style={{ color: '#eb2f96' }} />, label: '子任务' },
};

function getToolDisplay(tool: string): { icon: React.ReactNode; label: string } {
  const lower = tool.toLowerCase();
  return TOOL_META[lower] ?? { icon: <CodeOutlined style={{ color: '#8c8c8c' }} />, label: tool };
}

const ROW_BG = (index: number) => index % 2 === 0 ? '#fafafa' : 'transparent';

function StepItem({ step, index }: { step: OpenCodeStep; index: number }) {
  if (step.step_type === 'tool_use') {
    const { icon, label } = getToolDisplay(step.tool ?? 'unknown');
    return (
      <div
        style={{
          padding: '6px 12px',
          borderRadius: 4,
          background: ROW_BG(index),
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
          fontFamily: 'monospace',
        }}
      >
        {icon}
        <Typography.Text strong style={{ minWidth: 32 }}>
          {label}
        </Typography.Text>
        <Typography.Text
          code
          ellipsis
          style={{ flex: 1, maxWidth: '100%' }}
          title={step.target}
        >
          {step.target || '-'}
        </Typography.Text>
      </div>
    );
  }

  if (step.step_type === 'step') {
    // Structural step (step_start / step_finish)
    return (
      <div
        style={{
          padding: '4px 12px',
          borderRadius: 4,
          background: ROW_BG(index),
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 12,
        }}
      >
        <RocketOutlined style={{ color: '#8c8c8c' }} />
        <Typography.Text type="secondary" italic>
          {step.summary || '-'}
        </Typography.Text>
      </div>
    );
  }

  // text step
  return (
    <div
      style={{
        padding: '6px 12px',
        borderRadius: 4,
        background: ROW_BG(index),
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        fontSize: 13,
      }}
    >
      <MessageOutlined style={{ color: '#8c8c8c', marginTop: 2 }} />
      <Typography.Text
        type="secondary"
        style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          flex: 1,
        }}
      >
        {step.summary || '-'}
      </Typography.Text>
    </div>
  );
}

export function StepList({ steps, isRunning }: StepListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new steps arrive
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [steps.length]);

  if (steps.length === 0) {
    return (
      <Empty
        description={isRunning ? '等待执行步骤…' : '暂无步骤记录'}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  return (
    <div
      style={{
        lineHeight: 1.6,
      }}
    >
      {steps.map((step, i) => (
        <StepItem key={i} step={step} index={i} />
      ))}
      {isRunning && (
        <div style={{ padding: '8px 12px', textAlign: 'center' }}>
          <Spin size="small" />
          <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            AI 执行中…
          </Typography.Text>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
