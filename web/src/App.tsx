import { useState, useCallback } from 'react';
import { Layout, ConfigProvider, theme } from 'antd';
import { TopBar } from './components/TopBar';
import { KanbanBoard } from './components/KanbanBoard';
import { CardDetailModal } from './components/CardDetailModal';
import { useIssues } from './hooks/useIssues';
import { useIssueDetail } from './hooks/useIssueDetail';
import type { Issue } from './types';
import './App.css';

const { Content } = Layout;

function App() {
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null);

  const {
    issues,
    refresh: refreshIssues,
  } = useIssues();

  const {
    issue: detailedIssue,
    executions,
    logs,
    steps,
    loading: detailLoading,
    refresh: refreshDetail,
  } = useIssueDetail(selectedIssue?.id ?? null);

  const handleActionDone = useCallback(() => {
    refreshIssues();
    refreshDetail();
  }, [refreshIssues, refreshDetail]);

  const handleCardClick = useCallback((issue: Issue) => {
    setSelectedIssue(issue);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedIssue(null);
  }, []);

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <Layout style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
        <TopBar
          issues={issues}
          onCreated={refreshIssues}
          onRefresh={refreshIssues}
        />
        <Content style={{ flex: 1, overflow: 'hidden', background: '#f5f5f5' }}>
          <KanbanBoard
            issues={issues}
            onCardClick={handleCardClick}
          />
        </Content>
      </Layout>

      {/* Card Detail Modal — left/right split layout */}
      <CardDetailModal
        open={!!selectedIssue}
        issue={detailedIssue}
        executions={executions}
        logs={logs}
        steps={steps}
        loading={detailLoading}
        onClose={handleCloseDetail}
        onActionDone={handleActionDone}
      />
    </ConfigProvider>
  );
}

export default App;
