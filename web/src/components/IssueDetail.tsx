import { Descriptions, Tabs, Typography, Spin, Empty, Alert } from 'antd';
import {
  BranchesOutlined,
  FileTextOutlined,
  FolderOutlined,
  HistoryOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { IssueStatusTag } from './StatusTag';
import { ActionButtons } from './ActionButtons';
import { RetryInput } from './RetryInput';
import { ExecutionTimeline } from './ExecutionTimeline';
import { LogViewer } from './LogViewer';
import { StepList } from './StepList';
import type { Issue, Execution, ExecutionLog, OpenCodeStep } from '../types';

interface IssueDetailProps {
  issue: Issue | null;
  executions: Execution[];
  logs: ExecutionLog[];
  steps: OpenCodeStep[];
  loading: boolean;
  onActionDone: () => void;
}

export function IssueDetail({
  issue,
  executions,
  logs,
  steps,
  loading,
  onActionDone,
}: IssueDetailProps) {
  if (!issue) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Empty description="选择一个 Issue 查看详情" />
      </div>
    );
  }

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  const isWaiting = issue.status === 'failed' || issue.status === 'waiting_human';
  const isRunning = issue.status === 'running';

  return (
    <div style={{ padding: 24, height: '100%', overflow: 'auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {issue.title}
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          ID: {issue.id}
        </Typography.Text>
      </div>

      {/* Metadata */}
      <Descriptions
        bordered
        size="small"
        column={2}
        style={{ marginBottom: 16 }}
      >
        <Descriptions.Item label="状态">
          <IssueStatusTag status={issue.status} />
        </Descriptions.Item>
        <Descriptions.Item label="分支">
          {issue.branch_name ? (
            <Typography.Text code>
              <BranchesOutlined /> {issue.branch_name}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="工作目录">
          {issue.workspace ? (
            <Typography.Text code>
              <FolderOutlined /> {issue.workspace}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">默认</Typography.Text>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="创建时间">
          {new Date(issue.created_at).toLocaleString()}
        </Descriptions.Item>
        <Descriptions.Item label="更新时间">
          {new Date(issue.updated_at).toLocaleString()}
        </Descriptions.Item>
        {issue.description && (
          <Descriptions.Item label="描述" span={2}>
            <Typography.Paragraph
              style={{ margin: 0, whiteSpace: 'pre-wrap' }}
            >
              {issue.description}
            </Typography.Paragraph>
          </Descriptions.Item>
        )}
      </Descriptions>

      {/* Action buttons */}
      <div style={{ marginBottom: 16 }}>
        <ActionButtons
          issueId={issue.id}
          status={issue.status}
          onActionDone={onActionDone}
        />
      </div>

      {/* Waiting human alert + retry input */}
      {isWaiting && (
        <Alert
          type="warning"
          message="AI 执行失败，等待指令"
          description={
            <>
              {issue.failure_reason && <div>{issue.failure_reason}</div>}
              {issue.human_instruction && (
                <div style={{ marginTop: issue.failure_reason ? 8 : 0 }}>
                  上次指令: {issue.human_instruction}
                </div>
              )}
            </>
          }
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}
      <RetryInput
        issueId={issue.id}
        status={issue.status}
        failureReason={issue.failure_reason}
        currentWorkspace={issue.workspace}
        onRetryDone={onActionDone}
      />

      {/* Tabs: live steps + executions + logs */}
      <Tabs
        defaultActiveKey={isRunning ? 'steps' : 'executions'}
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'steps',
            label: (
              <span>
                <ThunderboltOutlined /> 实时步骤{steps.length > 0 ? ` (${steps.length})` : ''}
              </span>
            ),
            children: <StepList steps={steps} isRunning={isRunning} />,
          },
          {
            key: 'executions',
            label: (
              <span>
                <HistoryOutlined /> 执行历史 ({executions.length})
              </span>
            ),
            children: <ExecutionTimeline executions={executions} />,
          },
          {
            key: 'logs',
            label: (
              <span>
                <FileTextOutlined /> 执行日志 ({logs.length})
              </span>
            ),
            children: <LogViewer logs={logs} />,
          },
        ]}
      />
    </div>
  );
}
