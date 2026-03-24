import { useMemo } from 'react';
import { Modal, Typography, Tabs, Tag, Spin, Empty, Alert, Space, Divider } from 'antd';
import {
  BranchesOutlined,
  CloseOutlined,
  FileTextOutlined,
  FolderOutlined,
  HistoryOutlined,
  LinkOutlined,
  ThunderboltOutlined,
  CalendarOutlined,
} from '@ant-design/icons';
import { IssueStatusTag } from './StatusTag';
import { ActionButtons } from './ActionButtons';
import { RetryInput } from './RetryInput';
import { SpecCard } from './SpecCard';
import { ExecutionTimeline } from './ExecutionTimeline';
import { LogViewer } from './LogViewer';
import { StepList } from './StepList';
import { getColumnForIssue } from '../utils/kanban';
import { issueStatusLabel } from '../utils/status';
import type { Issue, Execution, ExecutionLog, OpenCodeStep } from '../types';

interface CardDetailModalProps {
  open: boolean;
  issue: Issue | null;
  executions: Execution[];
  logs: ExecutionLog[];
  steps: OpenCodeStep[];
  loading: boolean;
  onClose: () => void;
  onActionDone: () => void;
}

const PRIORITY_LABEL: Record<string, { text: string; color: string }> = {
  high: { text: 'HIGH', color: '#f5222d' },
  medium: { text: 'MED', color: '#fa8c16' },
  low: { text: 'LOW', color: '#8c8c8c' },
};

const COLUMN_LABEL: Record<string, string> = {
  backlog: 'Backlog',
  todo: 'Todo',
  dev: 'Dev',
  review: 'Review',
  done: 'Done',
};

export function CardDetailModal({
  open,
  issue,
  executions,
  logs,
  steps,
  loading,
  onClose,
  onActionDone,
}: CardDetailModalProps) {
  const isRunning = issue?.status === 'running';
  const isPlanning = issue?.status === 'planning';
  const isWaiting = issue?.status === 'waiting_human';

  const columnKey = useMemo(
    () => (issue ? getColumnForIssue(issue) : 'backlog'),
    [issue],
  );

  const defaultTab = useMemo(() => {
    if (isRunning || isPlanning) return 'steps';
    if (executions.length > 0) return 'executions';
    return 'steps';
  }, [isRunning, isPlanning, executions.length]);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width="90vw"
      style={{ top: 32 }}
      styles={{
        body: { padding: 0, height: 'calc(85vh - 55px)', overflow: 'hidden' },
      }}
      title={
        issue ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingRight: 24 }}>
            <span style={{ fontWeight: 600, fontSize: 15 }}>Card Detail</span>
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {issue.id.slice(0, 8)}…
            </Typography.Text>
          </div>
        ) : 'Card Detail'
      }
      closeIcon={<CloseOutlined />}
      destroyOnClose
    >
      {loading && !issue ? (
        <div className="cdm-loading">
          <Spin size="large" />
        </div>
      ) : !issue ? (
        <div className="cdm-loading">
          <Empty description="Issue 数据加载失败" />
        </div>
      ) : (
        <div className="cdm-body">
          {/* ===== Left Panel: Metadata + Actions + Spec ===== */}
          <div className="cdm-left">
            <div className="cdm-left-scroll">
              {/* Title */}
              <div className="cdm-section">
                <Typography.Text type="secondary" strong style={{ fontSize: 11, textTransform: 'uppercase' }}>
                  Title
                </Typography.Text>
                <Typography.Title level={5} style={{ margin: '4px 0 0' }}>
                  {issue.title}
                </Typography.Title>
              </div>

              {/* Objective / Description */}
              {issue.description && (
                <div className="cdm-section">
                  <Typography.Text type="secondary" strong style={{ fontSize: 11, textTransform: 'uppercase' }}>
                    Objective
                  </Typography.Text>
                  <Typography.Paragraph
                    style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', fontSize: 13 }}
                    ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
                  >
                    {issue.description}
                  </Typography.Paragraph>
                </div>
              )}

              {/* Priority & Column */}
              <div className="cdm-section">
                <Space size="large">
                  <div>
                    <Typography.Text type="secondary" strong style={{ fontSize: 11, textTransform: 'uppercase', display: 'block' }}>
                      Priority
                    </Typography.Text>
                    <Tag
                      color={PRIORITY_LABEL[issue.priority]?.color || '#8c8c8c'}
                      style={{ marginTop: 4 }}
                    >
                      {PRIORITY_LABEL[issue.priority]?.text || issue.priority}
                    </Tag>
                  </div>
                  <div>
                    <Typography.Text type="secondary" strong style={{ fontSize: 11, textTransform: 'uppercase', display: 'block' }}>
                      Column
                    </Typography.Text>
                    <Tag style={{ marginTop: 4 }}>{COLUMN_LABEL[columnKey] || columnKey}</Tag>
                  </div>
                  <div>
                    <Typography.Text type="secondary" strong style={{ fontSize: 11, textTransform: 'uppercase', display: 'block' }}>
                      Status
                    </Typography.Text>
                    <div style={{ marginTop: 4 }}>
                      <IssueStatusTag status={issue.status} />
                    </div>
                  </div>
                </Space>
              </div>

              <Divider style={{ margin: '12px 0' }} />

              {/* Action buttons */}
              <div className="cdm-section">
                <ActionButtons issueId={issue.id} status={issue.status} onActionDone={onActionDone} />
              </div>

              {/* Waiting human alert + retry input */}
              {isWaiting && (
                <div className="cdm-section">
                  <Alert
                    type="warning"
                    message="AI 执行失败，等待指令"
                    description={
                      <>
                        {issue.failure_reason && <div style={{ fontSize: 13 }}>{issue.failure_reason}</div>}
                        {issue.human_instruction && (
                          <div style={{ marginTop: issue.failure_reason ? 8 : 0, fontSize: 13 }}>
                            上次指令: {issue.human_instruction}
                          </div>
                        )}
                      </>
                    }
                    showIcon
                    style={{ marginBottom: 8 }}
                  />
                  <RetryInput
                    issueId={issue.id}
                    status={issue.status}
                    failureReason={issue.failure_reason}
                    currentWorkspace={issue.workspace}
                    onRetryDone={onActionDone}
                  />
                </div>
              )}

              {/* Spec card */}
              {issue.spec && (
                <div className="cdm-section">
                  <SpecCard
                    issueId={issue.id}
                    spec={issue.spec}
                    status={issue.status}
                    onActionDone={onActionDone}
                  />
                </div>
              )}

              <Divider style={{ margin: '12px 0' }} />

              {/* Metadata details */}
              <div className="cdm-section cdm-meta-grid">
                {issue.branch_name && (
                  <div className="cdm-meta-item">
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      <BranchesOutlined /> 分支
                    </Typography.Text>
                    <Typography.Text code style={{ fontSize: 12, wordBreak: 'break-all' }}>
                      {issue.branch_name}
                    </Typography.Text>
                  </div>
                )}
                {issue.pr_url && (
                  <div className="cdm-meta-item">
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      <LinkOutlined /> PR
                    </Typography.Text>
                    <a href={issue.pr_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                      {issue.pr_url}
                    </a>
                  </div>
                )}
                {issue.workspace && (
                  <div className="cdm-meta-item">
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      <FolderOutlined /> 工作目录
                    </Typography.Text>
                    <Typography.Text code style={{ fontSize: 12, wordBreak: 'break-all' }}>
                      {issue.workspace}
                    </Typography.Text>
                  </div>
                )}
                <div className="cdm-meta-item">
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    <CalendarOutlined /> 创建时间
                  </Typography.Text>
                  <Typography.Text style={{ fontSize: 12 }}>
                    {new Date(issue.created_at).toLocaleString()}
                  </Typography.Text>
                </div>
                <div className="cdm-meta-item">
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    <CalendarOutlined /> 更新时间
                  </Typography.Text>
                  <Typography.Text style={{ fontSize: 12 }}>
                    {new Date(issue.updated_at).toLocaleString()}
                  </Typography.Text>
                </div>
              </div>
            </div>
          </div>

          {/* ===== Right Panel: Real-time Session ===== */}
          <div className="cdm-right">
            <Tabs
              defaultActiveKey={defaultTab}
              style={{ height: '100%' }}
              className="cdm-tabs"
              items={[
                {
                  key: 'steps',
                  label: (
                    <span>
                      <ThunderboltOutlined /> 实时步骤
                      {steps.length > 0 ? ` (${steps.length})` : ''}
                    </span>
                  ),
                  children: (
                    <div className="cdm-tab-content">
                      <StepList steps={steps} isRunning={isRunning || isPlanning || false} />
                    </div>
                  ),
                },
                {
                  key: 'executions',
                  label: (
                    <span>
                      <HistoryOutlined /> 执行历史 ({executions.length})
                    </span>
                  ),
                  children: (
                    <div className="cdm-tab-content">
                      <ExecutionTimeline executions={executions} />
                    </div>
                  ),
                },
                {
                  key: 'logs',
                  label: (
                    <span>
                      <FileTextOutlined /> 执行日志 ({logs.length})
                    </span>
                  ),
                  children: (
                    <div className="cdm-tab-content">
                      <LogViewer logs={logs} />
                    </div>
                  ),
                },
              ]}
            />
          </div>
        </div>
      )}
    </Modal>
  );
}
