import { Tag } from 'antd';
import type { IssueStatus } from '../types';
import { issueStatusColor, issueStatusLabel } from '../utils/status';

interface IssueStatusTagProps {
  status: IssueStatus;
}

export function IssueStatusTag({ status }: IssueStatusTagProps) {
  return <Tag color={issueStatusColor[status]}>{issueStatusLabel[status]}</Tag>;
}
