import { Button, Space, Popconfirm, message } from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  UndoOutlined,
  ReloadOutlined,
  DeleteOutlined,
  EditOutlined,
} from '@ant-design/icons';
import {
  runIssue,
  cancelIssue,
  planIssue,
  rejectSpec,
  completeIssue,
  deleteIssue,
} from '../api/client';
import type { IssueStatus } from '../types';

type ActionKey = 'plan' | 'run' | 'cancel' | 'reject' | 'complete' | 'retry' | 'delete';

interface ActionDef {
  label: string;
  action: ActionKey;
  icon: React.ReactNode;
  type?: 'primary' | 'default' | 'dashed' | 'link' | 'text';
  danger?: boolean;
  confirm?: { title: string; description: string };
}

/**
 * Full status → action matrix per ROADMAP3 spec.
 *
 * Notes:
 * - `waiting_human` shows Retry here but the actual retry form is in RetryInput
 *   (displayed separately in CardDetailModal). This button triggers a simple
 *   no-instruction retry.
 * - `delete` is available for open/done/waiting_human/cancelled per ROADMAP3 step 1.
 * - Edit is handled inline in CardDetailModal, not as a button here.
 */
const ACTION_MATRIX: Record<IssueStatus, ActionDef[]> = {
  open: [
    {
      label: 'Refine',
      action: 'plan',
      icon: <ExperimentOutlined />,
      type: 'default',
    },
    {
      label: 'Run',
      action: 'run',
      icon: <PlayCircleOutlined />,
      type: 'primary',
    },
    {
      label: '删除',
      action: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
  planning: [
    {
      label: 'Cancel',
      action: 'cancel',
      icon: <StopOutlined />,
      danger: true,
      confirm: { title: '确认取消？', description: '正在生成的方案将被中止' },
    },
  ],
  planned: [
    {
      label: 'Run',
      action: 'run',
      icon: <PlayCircleOutlined />,
      type: 'primary',
    },
    {
      label: 'Reject',
      action: 'reject',
      icon: <UndoOutlined />,
      danger: true,
      confirm: { title: '确认拒绝 Spec？', description: 'Issue 将退回 Backlog' },
    },
  ],
  running: [
    {
      label: 'Cancel',
      action: 'cancel',
      icon: <StopOutlined />,
      danger: true,
      confirm: { title: '确认取消？', description: '正在执行的任务将被中止' },
    },
  ],
  review: [
    {
      label: 'Complete',
      action: 'complete',
      icon: <CheckCircleOutlined />,
      type: 'primary',
    },
  ],
  done: [
    {
      label: '删除',
      action: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
  waiting_human: [
    {
      label: '删除',
      action: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
  cancelled: [
    {
      label: 'Restart',
      action: 'run',
      icon: <ReloadOutlined />,
      type: 'primary',
    },
    {
      label: '删除',
      action: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      confirm: { title: '确认删除？', description: '此操作不可撤销' },
    },
  ],
};

const ACTION_SUCCESS_MSG: Record<ActionKey, string> = {
  plan: '已触发方案生成',
  run: '已触发 AI 执行',
  cancel: '已取消执行',
  reject: 'Spec 已拒绝，Issue 退回 Backlog',
  complete: '已标记完成',
  retry: '已触发重试',
  delete: '已删除',
};

interface ActionButtonsProps {
  issueId: string;
  status: IssueStatus;
  onActionDone: () => void;
  /** Compact mode for card hover actions — smaller buttons, no labels */
  compact?: boolean;
}

export function ActionButtons({ issueId, status, onActionDone, compact }: ActionButtonsProps) {
  const actions = ACTION_MATRIX[status] ?? [];

  if (actions.length === 0) return null;

  const executeAction = async (action: ActionKey) => {
    try {
      switch (action) {
        case 'plan':
          await planIssue(issueId);
          break;
        case 'run':
        case 'retry':
          await runIssue(issueId);
          break;
        case 'cancel':
          await cancelIssue(issueId);
          break;
        case 'reject':
          await rejectSpec(issueId);
          break;
        case 'complete':
          await completeIssue(issueId);
          break;
        case 'delete':
          await deleteIssue(issueId);
          break;
      }
      message.success(ACTION_SUCCESS_MSG[action]);
      onActionDone();
    } catch (err: any) {
      message.error('操作失败: ' + (err?.message || '未知错误'));
    }
  };

  const buttonSize = compact ? 'small' as const : 'middle' as const;

  return (
    <Space size="small" wrap>
      {actions.map((def) => {
        const btn = (
          <Button
            key={def.action + def.label}
            size={buttonSize}
            type={def.type ?? 'default'}
            danger={def.danger}
            icon={def.icon}
            onClick={def.confirm ? undefined : () => executeAction(def.action)}
          >
            {compact ? null : def.label}
          </Button>
        );

        if (def.confirm) {
          return (
            <Popconfirm
              key={def.action + def.label}
              title={def.confirm.title}
              description={def.confirm.description}
              onConfirm={() => executeAction(def.action)}
              okText="确认"
              cancelText="取消"
            >
              {btn}
            </Popconfirm>
          );
        }
        return btn;
      })}
    </Space>
  );
}
