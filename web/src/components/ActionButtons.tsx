import { Button, Space, Popconfirm, message } from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { runIssue, cancelIssue } from '../api/client';
import type { IssueStatus } from '../types';

interface ActionButtonsProps {
  issueId: string;
  status: IssueStatus;
  onActionDone: () => void;
}

export function ActionButtons({ issueId, status, onActionDone }: ActionButtonsProps) {
  const canRun = status === 'open' || status === 'waiting_human';
  const canCancel = status === 'running';

  const handleRun = async () => {
    try {
      await runIssue(issueId);
      message.success('已触发 AI 执行');
      onActionDone();
    } catch (err: any) {
      message.error('执行失败: ' + (err?.message || '未知错误'));
    }
  };

  const handleCancel = async () => {
    try {
      await cancelIssue(issueId);
      message.success('已取消执行');
      onActionDone();
    } catch (err: any) {
      message.error('取消失败: ' + (err?.message || '未知错误'));
    }
  };

  return (
    <Space>
      {canRun && (
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          onClick={handleRun}
        >
          AI 执行
        </Button>
      )}
      {canCancel && (
        <Popconfirm
          title="确认取消？"
          description="正在执行的任务将被中止"
          onConfirm={handleCancel}
          okText="确认"
          cancelText="取消"
        >
          <Button danger icon={<StopOutlined />}>
            取消执行
          </Button>
        </Popconfirm>
      )}
    </Space>
  );
}
