import { useState } from 'react';
import { Modal, Form, Input, message } from 'antd';
import { createIssue } from '../api/client';

interface IssueFormProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function IssueForm({ open, onClose, onCreated }: IssueFormProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await createIssue({
        title: values.title,
        description: values.description || '',
        workspace: values.workspace || undefined,
      });
      message.success('Issue 创建成功');
      form.resetFields();
      onCreated();
    } catch (err: any) {
      if (err?.errorFields) return; // validation error
      message.error('创建失败: ' + (err?.message || '未知错误'));
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
      <Form form={form} layout="vertical">
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
        <Form.Item
          name="workspace"
          label="工作目录"
          tooltip="Agent 执行任务的代码仓库路径。留空则使用全局默认配置。"
        >
          <Input placeholder="/path/to/your/repo（可选，留空使用默认配置）" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
