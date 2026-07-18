import { Alert, Descriptions, Empty, Modal, Spin, Typography } from 'antd';
import { CloseOutlined } from '@ant-design/icons';
import { ActionButtons } from './ActionButtons';
import { IssueStatusTag } from './StatusTag';
import type { Issue } from '../types';

interface CardDetailModalProps {
  open: boolean;
  issue: Issue | null;
  loading: boolean;
  onClose: () => void;
  onActionDone: () => void;
}

function formatTimestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

export function CardDetailModal({
  open,
  issue,
  loading,
  onClose,
  onActionDone,
}: CardDetailModalProps) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="Issue 详情"
      closeIcon={<CloseOutlined />}
      destroyOnClose
    >
      {loading && !issue ? (
        <div className="cdm-loading"><Spin size="large" /></div>
      ) : !issue ? (
        <div className="cdm-loading"><Empty description="Issue 数据加载失败" /></div>
      ) : (
        <div>
          <Typography.Title level={5}>{issue.content}</Typography.Title>
          <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="项目">{issue.project}</Descriptions.Item>
            <Descriptions.Item label="状态"><IssueStatusTag status={issue.status} /></Descriptions.Item>
            <Descriptions.Item label="创建时间">{formatTimestamp(issue.created_at)}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{formatTimestamp(issue.updated_at)}</Descriptions.Item>
            <Descriptions.Item label="结束时间">{formatTimestamp(issue.finished_at)}</Descriptions.Item>
          </Descriptions>

          <div style={{ marginBottom: 16 }}>
            <ActionButtons issueId={issue.id} status={issue.status} onActionDone={onActionDone} />
          </div>

          {issue.outcome === 'success' && (
            <section>
              <Typography.Title level={5}>cc-connect 结果</Typography.Title>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                {issue.result || '-'}
              </Typography.Paragraph>
            </section>
          )}
          {issue.outcome === 'error' && (
            <Alert
              type="error"
              showIcon
              message="cc-connect 执行失败"
              description={issue.error_message || 'cc-connect 未提供错误详情'}
            />
          )}
        </div>
      )}
    </Modal>
  );
}
