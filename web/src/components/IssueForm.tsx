import { useState } from 'react';
import { Button, Modal, Form, Input, Select, Space, message } from 'antd';
import { FolderOpenOutlined } from '@ant-design/icons';
import { createIssue, selectWorkspace } from '../api/client';
import type { AgentType, IssuePriority } from '../types';

interface IssueFormProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const PRIORITY_OPTIONS: Array<{ label: string; value: IssuePriority }> = [
  { label: 'High', value: 'high' },
  { label: 'Medium', value: 'medium' },
  { label: 'Low', value: 'low' },
];

const AGENT_OPTIONS: Array<{ label: string; value: AgentType }> = [
  { label: 'WisCode', value: 'wiscode' },
];

function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : '未知错误';
}

export function IssueForm({ open, onClose, onCreated }: IssueFormProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [selectingWorkspace, setSelectingWorkspace] = useState(false);

  const handleSelectWorkspace = async () => {
    try {
      setSelectingWorkspace(true);
      const { workspace } = await selectWorkspace();
      if (workspace) form.setFieldValue('workspace', workspace);
    } catch (err: unknown) {
      message.error('无法打开目录选择窗口: ' + errorMessage(err));
    } finally {
      setSelectingWorkspace(false);
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await createIssue({
        title: values.title,
        description: values.description || '',
        workspace: values.workspace || undefined,
        priority: values.priority || 'medium',
        agent: values.agent || 'wiscode',
      });
      message.success('Issue 创建成功');
      form.resetFields();
      onCreated();
    } catch (err: unknown) {
      if (typeof err === 'object' && err !== null && 'errorFields' in err) return;
      message.error('创建失败: ' + errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="新建 Issue"
      open={open}
      onOk={handleSubmit}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      confirmLoading={loading}
      okText="创建"
      cancelText="取消"
    >
      <Form form={form} layout="vertical" initialValues={{ priority: 'medium', agent: 'wiscode' }}>
        <Form.Item
          name="title"
          label="标题"
          rules={[{ required: true, message: '请输入标题' }]}
        >
          <Input placeholder="简要描述任务" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea
            rows={4}
            placeholder="详细描述任务内容（可选）"
          />
        </Form.Item>
        <Form.Item name="priority" label="优先级">
          <Select options={PRIORITY_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="agent"
          label="Agent"
          rules={[{ required: true, message: '请选择 Agent' }]}
        >
          <Select options={AGENT_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="workspace"
          label="工作目录"
          tooltip="Agent 执行任务的代码仓库路径。留空则使用全局默认配置。"
        >
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item name="workspace" noStyle>
              <Input readOnly placeholder="选择代码仓库目录（可选，留空使用默认配置）" />
            </Form.Item>
            <Button
              icon={<FolderOpenOutlined />}
              loading={selectingWorkspace}
              onClick={handleSelectWorkspace}
            >
              选择目录
            </Button>
          </Space.Compact>
        </Form.Item>
      </Form>
    </Modal>
  );
}
