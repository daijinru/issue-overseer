import { useEffect, useState } from 'react';
import { Alert, Form, Input, Modal, message } from 'antd';
import { createIssue, getCCConnectProjects } from '../api/client';
import type { CCConnectProject } from '../types';

interface IssueFormProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function errorMessage(err: unknown) {
  return err instanceof Error ? err.message : '未知错误';
}

export function IssueForm({ open, onClose, onCreated }: IssueFormProps) {
  const [content, setContent] = useState('');
  const [project, setProject] = useState('');
  const [projects, setProjects] = useState<CCConnectProject[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoadingProjects(true);
    setProjectError(null);

    void getCCConnectProjects()
      .then((discoveredProjects) => {
        if (cancelled) return;
        setProjects(discoveredProjects);
        setProject((currentProject) => currentProject || discoveredProjects[0]?.name || '');
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setProjects([]);
          setProject('');
          setProjectError(errorMessage(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingProjects(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  const resetAndClose = () => {
    setContent('');
    setProject('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!content.trim() || !project) return;

    try {
      setSubmitting(true);
      await createIssue({ content: content.trim(), project });
      message.success('Issue 创建成功');
      setContent('');
      setProject('');
      onCreated();
    } catch (err: unknown) {
      message.error('创建失败: ' + errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submitDisabled = loadingProjects || !!projectError || !content.trim() || !project;

  return (
    <Modal
      title="新建 Issue"
      open={open}
      onOk={handleSubmit}
      onCancel={resetAndClose}
      confirmLoading={submitting}
      okButtonProps={{ disabled: submitDisabled }}
      okText="创建"
      cancelText="取消"
    >
      <Form layout="vertical">
        <Form.Item label={<label htmlFor="issue-content">任务目标</label>} required>
          <Input.TextArea
            id="issue-content"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={5}
            placeholder="描述需要 cc-connect Agent 完成的任务"
          />
        </Form.Item>
        <Form.Item label={<label htmlFor="issue-project">Agent</label>} required>
          <select
            id="issue-project"
            value={project}
            onChange={(event) => setProject(event.target.value)}
            disabled={loadingProjects || !!projectError}
            style={{ width: '100%', minHeight: 32, borderColor: '#d9d9d9', borderRadius: 6, padding: '4px 11px' }}
          >
            <option value="" disabled>{loadingProjects ? '正在加载项目…' : '请选择 cc-connect 项目'}</option>
            {projects.map((availableProject) => (
              <option key={availableProject.name} value={availableProject.name}>
                {availableProject.name}
              </option>
            ))}
          </select>
        </Form.Item>
        {projectError && (
          <Alert
            type="error"
            showIcon
            message="无法加载 cc-connect 项目"
            description={projectError}
          />
        )}
      </Form>
    </Modal>
  );
}
