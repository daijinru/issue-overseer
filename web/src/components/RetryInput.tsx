import { useState } from 'react';
import { Input, Button, Space, message } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { retryIssue } from '../api/client';
import type { IssueStatus } from '../types';

interface RetryInputProps {
  issueId: string;
  status: IssueStatus;
  onRetryDone: () => void;
}

export function RetryInput({ issueId, status, onRetryDone }: RetryInputProps) {
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);

  const canRetry = status === 'failed' || status === 'waiting_human';

  if (!canRetry) return null;

  const handleRetry = async () => {
    try {
      setLoading(true);
      await retryIssue(issueId, {
        human_instruction: instruction || undefined,
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
