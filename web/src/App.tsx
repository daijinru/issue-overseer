import { useState, useCallback } from 'react';
import { Layout, ConfigProvider, theme } from 'antd';
import { IssueList } from './components/IssueList';
import { IssueDetail } from './components/IssueDetail';
import { useIssues } from './hooks/useIssues';
import { useIssueDetail } from './hooks/useIssueDetail';
import './App.css';

const { Sider, Content } = Layout;

function App() {
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);

  const {
    issues,
    loading: issuesLoading,
    statusFilter,
    setStatusFilter,
    refresh: refreshIssues,
  } = useIssues();

  const {
    issue: selectedIssue,
    executions,
    logs,
    steps,
    loading: detailLoading,
    refresh: refreshDetail,
  } = useIssueDetail(selectedIssueId);

  const handleActionDone = useCallback(() => {
    refreshIssues();
    refreshDetail();
  }, [refreshIssues, refreshDetail]);

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <Layout style={{ height: '100vh' }}>
        <Sider
          width={360}
          theme="light"
          style={{
            borderRight: '1px solid #f0f0f0',
            overflow: 'hidden',
          }}
        >
          <IssueList
            issues={issues}
            loading={issuesLoading}
            selectedId={selectedIssueId}
            statusFilter={statusFilter}
            onSelect={setSelectedIssueId}
            onStatusFilterChange={setStatusFilter}
            onRefresh={refreshIssues}
            onCreated={() => {
              refreshIssues();
            }}
          />
        </Sider>
        <Content style={{ background: '#fff', overflow: 'hidden' }}>
          <IssueDetail
            issue={selectedIssue}
            executions={executions}
            logs={logs}
            steps={steps}
            loading={detailLoading}
            onActionDone={handleActionDone}
          />
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
