import { useState } from 'react';
import { Input, Button, Space, message, Typography } from 'antd';
import { SendOutlined, FolderOutlined } from '@ant-design/icons';
import { retryIssue } from '../api/client';
import type { IssueStatus } from '../types';

interface RetryInputProps {
  issueId: string;
  status: IssueStatus;
  failureReason?: string | null;
  currentWorkspace?: string | null;
  onRetryDone: () => void;
}

export function RetryInput({ issueId, status, failureReason, currentWorkspace, onRetryDone }: RetryInputProps) {
  const [instruction, setInstruction] = useState('');
  const [workspace, setWorkspace] = useState(currentWorkspace ?? '');
  const [loading, setLoading] = useState(false);

  const canRetry = status === 'failed' || status === 'waiting_human';

  // Highlight workspace input when the failure is about workspace / git repo
  const isWorkspaceError = failureReason
    ? /工作目录|git 仓库|不是有效的/.test(failureReason)
    : false;

  if (!canRetry) return null;

  const handleRetry = async () => {
    // Only send workspace if user actually changed it
    const workspaceChanged = workspace && workspace !== (currentWorkspace ?? '');
    try {
      setLoading(true);
      await retryIssue(issueId, {
        human_instruction: instruction || undefined,
        workspace: workspaceChanged ? workspace : undefined,
      });
      message.success('已触发重试');
      setInstruction('');
      onRetryDone();
    } catch (err: any) {
      message.error('重试失败: ' + (err?.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: 16 }}>
      {/* Workspace — always visible so user can correct it */}
      <div style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          <FolderOutlined /> 工作目录（git 仓库根目录）
        </Typography.Text>
        <Input
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          placeholder="输入仓库绝对路径，例如: /home/user/projects/my-repo"
          style={{ marginTop: 4 }}
          prefix={<FolderOutlined />}
          status={isWorkspaceError ? 'error' : undefined}
          allowClear
        />
        {isWorkspaceError && (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            上次执行因工作目录错误而失败，请修正路径后重试
          </Typography.Text>
        )}
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="输入附加指令（可选），例如：试试 pytest -x 只跑失败的那个测试"
          autoSize={{ minRows: 2, maxRows: 4 }}
          style={{ flex: 1 }}
        />
      </Space.Compact>
      <Button
        type="primary"
        icon={<SendOutlined />}
        onClick={handleRetry}
        loading={loading}
        style={{ marginTop: 8 }}
      >
        附加指令重试
      </Button>
    </div>
  );
}
