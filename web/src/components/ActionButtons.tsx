import { Button, Popconfirm, Space, message } from 'antd';
import { DeleteOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons';
import { cancelIssue, deleteIssue, runIssue } from '../api/client';
import type { IssueStatus } from '../types';

type ActionKey = 'run' | 'cancel' | 'delete';

interface ActionDef {
  label: string;
  action: ActionKey;
  icon: React.ReactNode;
  type?: 'primary' | 'default';
  danger?: boolean;
  confirm?: { title: string; description: string };
}

const ACTION_MATRIX: Record<IssueStatus, ActionDef[]> = {
  pending: [
    { label: '执行', action: 'run', icon: <PlayCircleOutlined />, type: 'primary' },
    {
      label: '删除', action: 'delete', icon: <DeleteOutlined />, danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
  running: [
    {
      label: '取消', action: 'cancel', icon: <StopOutlined />, danger: true,
      confirm: { title: '确认取消？', description: '正在执行的任务将被中止' },
    },
  ],
  finished: [
    {
      label: '删除', action: 'delete', icon: <DeleteOutlined />, danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
};

interface ActionButtonsProps {
  issueId: string;
  status: IssueStatus;
  onActionDone: () => void;
  compact?: boolean;
}

export function ActionButtons({ issueId, status, onActionDone, compact }: ActionButtonsProps) {
  const actions = ACTION_MATRIX[status];

  const executeAction = async (action: ActionKey) => {
    try {
      if (action === 'run') await runIssue(issueId);
      if (action === 'cancel') await cancelIssue(issueId);
      if (action === 'delete') await deleteIssue(issueId);
      message.success(action === 'delete' ? '已删除' : action === 'cancel' ? '已取消执行' : '已触发执行');
      onActionDone();
    } catch (err: unknown) {
      message.error('操作失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  return (
    <Space size="small" wrap>
      {actions.map((def) => {
        const button = (
          <Button
            key={def.action}
            size={compact ? 'small' : 'middle'}
            type={def.type ?? 'default'}
            danger={def.danger}
            icon={def.icon}
            onClick={def.confirm ? undefined : () => void executeAction(def.action)}
          >
            {compact ? null : def.label}
          </Button>
        );

        return def.confirm ? (
          <Popconfirm
            key={def.action}
            title={def.confirm.title}
            description={def.confirm.description}
            onConfirm={() => void executeAction(def.action)}
            okText="确认"
            cancelText="取消"
          >
            {button}
          </Popconfirm>
        ) : button;
      })}
    </Space>
  );
}
