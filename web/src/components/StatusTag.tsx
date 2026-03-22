import { Tag } from 'antd';
import type { IssueStatus, ExecutionStatus } from '../types';
import { issueStatusColor, issueStatusLabel, executionStatusColor, executionStatusLabel } from '../utils/status';

interface IssueStatusTagProps {
  status: IssueStatus;
}

export function IssueStatusTag({ status }: IssueStatusTagProps) {
  return <Tag color={issueStatusColor[status]}>{issueStatusLabel[status]}</Tag>;
}

interface ExecutionStatusTagProps {
  status: ExecutionStatus;
}

export function ExecutionStatusTag({ status }: ExecutionStatusTagProps) {
  return <Tag color={executionStatusColor[status]}>{executionStatusLabel[status]}</Tag>;
}
