import { useState } from 'react';
import { Card, Typography, Tag, List, Button, Space, Input, message, Popconfirm } from 'antd';
import {
  FileOutlined,
  CheckCircleOutlined,
  EditOutlined,
  CloseOutlined,
  SaveOutlined,
  ExperimentOutlined,
  UndoOutlined,
} from '@ant-design/icons';
import { rejectSpec, updateSpec } from '../api/client';
import type { IssueStatus } from '../types';

interface SpecData {
  plan: string;
  acceptance_criteria: string[];
  files_to_modify: string[];
  estimated_complexity: string;
}

interface SpecCardProps {
  issueId: string;
  spec: string;            // JSON string from issue.spec
  status: IssueStatus;
  onActionDone: () => void;
}

const COMPLEXITY_COLOR: Record<string, string> = {
  low: 'green',
  medium: 'orange',
  high: 'red',
};

function parseSpec(raw: string): SpecData | null {
  try {
    const data = JSON.parse(raw);
    return {
      plan: data.plan ?? '',
      acceptance_criteria: data.acceptance_criteria ?? data.acceptanceCriteria ?? [],
      files_to_modify: data.files_to_modify ?? data.filesToModify ?? [],
      estimated_complexity: data.estimated_complexity ?? data.complexity ?? 'medium',
    };
  } catch {
    return null;
  }
}

export function SpecCard({ issueId, spec, status, onActionDone }: SpecCardProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(spec);
  const [saving, setSaving] = useState(false);

  const parsed = parseSpec(spec);
  const canEdit = status === 'planned';
  const canReject = status === 'planned';

  const handleSave = async () => {
    // Validate JSON before saving
    try {
      JSON.parse(editValue);
    } catch {
      message.error('Spec 必须是有效的 JSON 格式');
      return;
    }
    try {
      setSaving(true);
      await updateSpec(issueId, editValue);
      message.success('Spec 已更新');
      setEditing(false);
      onActionDone();
    } catch (err: any) {
      message.error('更新失败: ' + (err?.message || '未知错误'));
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async () => {
    try {
      await rejectSpec(issueId);
      message.success('Spec 已拒绝，Issue 退回 Backlog');
      onActionDone();
    } catch (err: any) {
      message.error('拒绝失败: ' + (err?.message || '未知错误'));
    }
  };

  // Raw editing mode
  if (editing) {
    return (
      <Card
        size="small"
        title={<span><ExperimentOutlined /> 编辑 Spec</span>}
        style={{ marginBottom: 16 }}
        extra={
          <Space size="small">
            <Button
              size="small"
              icon={<SaveOutlined />}
              type="primary"
              onClick={handleSave}
              loading={saving}
            >
              保存
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              onClick={() => { setEditing(false); setEditValue(spec); }}
            >
              取消
            </Button>
          </Space>
        }
      >
        <Input.TextArea
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          autoSize={{ minRows: 6, maxRows: 16 }}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </Card>
    );
  }

  // Parsed display mode
  if (!parsed) {
    return (
      <Card
        size="small"
        title={<span><ExperimentOutlined /> Spec</span>}
        style={{ marginBottom: 16 }}
      >
        <Typography.Text type="secondary">Spec 数据解析失败</Typography.Text>
        <pre style={{ fontSize: 11, marginTop: 8, maxHeight: 200, overflow: 'auto' }}>{spec}</pre>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title={
        <span>
          <ExperimentOutlined style={{ marginRight: 6 }} />
          执行计划
          <Tag
            color={COMPLEXITY_COLOR[parsed.estimated_complexity] || 'default'}
            style={{ marginLeft: 8 }}
          >
            {parsed.estimated_complexity.toUpperCase()}
          </Tag>
        </span>
      }
      style={{ marginBottom: 16 }}
      extra={
        canEdit && (
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => setEditing(true)}
          >
            编辑
          </Button>
        )
      }
    >
      {/* Plan description */}
      {parsed.plan && (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>方案描述</Typography.Text>
          <Typography.Paragraph style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', fontSize: 13 }}>
            {parsed.plan}
          </Typography.Paragraph>
        </div>
      )}

      {/* Acceptance criteria */}
      {parsed.acceptance_criteria.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Typography.Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>
            <CheckCircleOutlined style={{ marginRight: 4 }} />
            验收标准
          </Typography.Text>
          <List
            size="small"
            dataSource={parsed.acceptance_criteria}
            renderItem={(item) => (
              <List.Item style={{ padding: '4px 0', borderBottom: 'none' }}>
                <Typography.Text style={{ fontSize: 13 }}>• {item}</Typography.Text>
              </List.Item>
            )}
            style={{ marginTop: 4 }}
          />
        </div>
      )}

      {/* Files to modify */}
      {parsed.files_to_modify.length > 0 && (
        <div style={{ marginBottom: canReject ? 12 : 0 }}>
          <Typography.Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>
            <FileOutlined style={{ marginRight: 4 }} />
            待修改文件
          </Typography.Text>
          <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {parsed.files_to_modify.map((file) => (
              <Tag key={file} style={{ fontSize: 11, fontFamily: 'monospace' }}>{file}</Tag>
            ))}
          </div>
        </div>
      )}

      {/* Reject button */}
      {canReject && (
        <div style={{ marginTop: 12, borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
          <Popconfirm
            title="确认拒绝 Spec？"
            description="Issue 将退回 Backlog（open 状态）"
            onConfirm={handleReject}
            okText="确认"
            cancelText="取消"
          >
            <Button size="small" icon={<UndoOutlined />} danger>
              拒绝方案
            </Button>
          </Popconfirm>
        </div>
      )}
    </Card>
  );
}
