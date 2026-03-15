# Claude Overseer — MVP 架构设计

> 精简自 OpenClaw 的自动化开发流水线。只做一件事：**Issue 进来，代码出去。**

---

## 1. MVP 范围

### 保留（核心路径）

- Issue CRUD + 状态流转
- Issue → Agent Task 转换（手动触发）
- Agent Task 队列 + 调度
- Agent 执行管线（LLM + 工具调用）
- Git Worktree 工作区隔离（作为 Agent 工具，由 Agent 自主调用）
- Memory（任务级经验记忆，KV 存储，Agent 通过工具读写，跨任务复用项目知识）
- REST API（HTTP only）
- SQLite 存储

### 移除（推迟到后续版本）

| 移除项 | 理由 | 推迟到 |
|--------|------|--------|
| Auth (JWT/API Key) | 单用户本地部署，不需要认证 | v1.5 |
| WebSocket Hub | MVP 用轮询或 SSE 替代，减少复杂度 | v1.5 |
| Comment Service | MVP 的 Issue 不需要评论系统 | v1.5 |
| Label / Milestone | 用 `type` 字段替代标签，不做里程碑 | v1.5 |
| Config 热重载 / Watcher | 改配置重启即可 | v2.0 |
| SecretRef ($env/$file) | 直接读环境变量 | v2.0 |
| 模型降级 (fallback) | MVP 只配一个模型 | v1.5 |
| FTS5 代码库知识索引 | 全文索引是重功能，MVP 只做轻量 KV 记忆 | v2.0 |
| AuditLog | MVP 不做审计 | v2.0 |
| 任务依赖 DAG | MVP 每个 Issue 只生成 1 个 Task | v1.5 |
| Web UI | MVP 只提供 API，用 curl/脚本交互 | v1.5 |
| Notifications / Webhooks | MVP 不做通知 | v2.0 |

---

## 2. 架构

```
         curl / 脚本 / 未来 Web UI
                  │
                  │ HTTP (REST)
                  ▼
┌──────────────────────────────────────────────────────────────┐
│              HTTP Server (单进程, Hono / Fastify)              │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  LAYER 1: Issue Service                                 │ │
│  │  ┌──────────────┐  ┌─────────────────────┐             │ │
│  │  │ Issue CRUD   │  │ IssueToTaskConverter│             │ │
│  │  │ + 状态流转    │  │ (Issue → AgentTask) │             │ │
│  │  └──────────────┘  └────────┬────────────┘             │ │
│  └─────────────────────────────┼───────────────────────────┘ │
│                                │                              │
│  ┌─────────────────────────────▼───────────────────────────┐ │
│  │  LAYER 2: Agent Runtime                                 │ │
│  │                                                          │ │
│  │  ┌────────────┐  ┌──────────────────────────────────┐  │ │
│  │  │ Task Queue │  │ Runner (调度 → Agent Runtime)     │  │ │
│  │  │ + Scheduler│  │                                    │  │ │
│  │  └────────────┘  │  ┌──────────────────────────────┐ │  │ │
│  │                   │  │ Agent Runtime (唯一的运行时)  │ │  │ │
│  │                   │  │ runTask → runTurn → runAttempt│ │  │ │
│  │                   │  │                              │ │  │ │
│  │                   │  │ ┌─ Tool Registry ──────────┐ │ │  │ │
│  │                   │  │ │ worktree_create/cleanup  │ │ │  │ │
│  │                   │  │ │ file_read/write/search   │ │ │  │ │
│  │                   │  │ │ shell_exec · git_ops     │ │ │  │ │
│  │                   │  │ │ git_push · github_pr     │ │ │  │ │
│  │                   │  │ │ memory_read/extract      │ │ │  │ │
│  │                   │  │ │ claude_code (委托子任务)  │ │ │  │ │
│  │                   │  │ └──────────────────────────┘ │ │  │ │
│  │                   │  └──────────────────────────────┘ │  │ │
│  │                   └──────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SQLite (issues · agent_tasks · executions · memory)    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 核心设计：Agent Runtime（唯一的运行时）

**没有 AgentBackend 接口，没有可插拔后端。** 只有一个 Agent Runtime。

跟 OpenClaw 彻底对齐：Agent Runtime 就是那个 Agent。它自己管理 LLM 对话、
工具调用、工作区创建、代码编写、推送、PR 创建。所有外部能力（包括 Claude Code CLI）
都是工具箱里的工具，不是运行时的替代品。

```
Agent Runtime (唯一)
  └── Tool Registry (工具箱)
        ├── worktree_create      # git worktree add
        ├── worktree_cleanup     # git worktree remove
        ├── file_read            # 读文件
        ├── file_write           # 写文件
        ├── file_search          # grep / glob
        ├── shell_exec           # 执行 shell 命令
        ├── git_ops              # git add/commit/diff/log
        ├── git_push             # git push
        ├── github_pr            # 创建 PR
        ├── memory_read          # 读取跨任务积累的项目知识
        ├── memory_extract       # 从当前对话历史中结构化提取经验记忆并保存
        └── claude_code          # 委托子任务给 Claude Code CLI
```

**`claude_code` 是工具，不是运行时。** Agent 在执行任务时，可以选择把某个子任务
委托给 Claude Code CLI 去做（比如"在这个 worktree 里实现 API endpoint"），
但决策权在 Agent Runtime，不在 Claude Code。

### Agent Runtime 输入输出

```typescript
interface AgentRunParams {
  task: AgentTask;
  issue: Issue;
  abortSignal?: AbortSignal;
}

interface AgentRunResult {
  success: boolean;
  summary: string;               // Agent 对完成情况的总结
  filesModified: string[];
  pullRequestUrl?: string;       // Agent 自己创建的 PR
  workspacePath?: string;        // Agent 创建的工作区路径（用于审查）
  error?: string;
}
```

### Agent Runtime 3 层执行管线

跟 OpenClaw 一样，自己管理 LLM 对话、工具调用解析、上下文窗口。
**Agent 管一切**：通过工具自己创建 worktree、写代码、推送、创建 PR。

```
┌─────────────────────────────────────────────────────────┐
│  AgentRuntime.run(params)                                │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  runTask(context)                                   │  │
│  │    · 构建 system prompt (角色 + 任务描述 + 仓库上下文)│  │
│  │    · 注入已有 Memory (项目知识) 到 system prompt     │  │
│  │    · 初始化对话 messages[]                           │  │
│  │    · 循环调用 runTurn() 直到任务完成或失败            │  │
│  │    · Agent 在收尾阶段调用 memory_extract 提取经验     │  │
│  │    · git commit 结果文件                             │  │
│  │                                                     │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  runTurn(messages)                            │   │  │
│  │  │    · 检查 token 预算，必要时截断上下文          │   │  │
│  │  │    · 调用 runAttempt()，失败时模型降级重试      │   │  │
│  │  │    · primary → fallback[0] → fallback[1] → 报错│   │  │
│  │  │                                               │   │  │
│  │  │  ┌────────────────────────────────────────┐   │   │  │
│  │  │  │  runAttempt(model, messages)            │   │   │  │
│  │  │  │    · 单次 LLM API 调用                   │   │   │  │
│  │  │  │    · 流式接收响应                         │   │   │  │
│  │  │  │    · 解析 tool_use blocks                │   │   │  │
│  │  │  │    · 执行工具 → 收集 tool_result          │   │   │  │
│  │  │  │    · 拼装 assistant+tool_result 消息      │   │   │  │
│  │  │  │    · 判断是否需要继续 (有 tool_use → 继续) │   │   │  │
│  │  │  └────────────────────────────────────────┘   │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

```typescript
class AgentRuntime {
  private modelProvider: ModelProvider;
  private toolRegistry: ToolRegistry;

  async run(params: AgentRunParams): Promise<AgentRunResult> {
    return this.runTask(params);
  }

  // ═══ Layer 1: runTask — 任务级编排 ═══
  private async runTask(params: AgentRunParams): Promise<AgentRunResult> {
    const { task, issue, abortSignal } = params;

    // 1. 构建系统提示词（包含所有工具的使用指引 + 已有项目知识记忆）
    const systemPrompt = this.buildSystemPrompt(issue, task);

    // 2. 初始化对话
    const messages: Message[] = [
      { role: 'user', content: this.buildTaskPrompt(issue, task) }
    ];

    // 3. Agent 循环 — 跟 OpenClaw 的 runReplyAgent 同构
    //    Agent 可通过 memory_read 获取已有项目知识
    //    然后调用 worktree_create → 写代码 → git push → github_pr → worktree_cleanup
    //    收尾阶段调用 memory_extract 从对话历史中提取经验记忆
    //    也可能调用 claude_code 工具委托子任务
    let turnCount = 0;
    const maxTurns = this.config.maxTurns ?? 50;

    while (turnCount < maxTurns) {
      abortSignal?.throwIfAborted();

      const turnResult = await this.runTurn(systemPrompt, messages);
      turnCount++;

      messages.push(...turnResult.newMessages);

      if (!turnResult.hasToolCalls) {
        return this.extractResult(turnResult.finalText);
      }
    }

    return { success: false, summary: '', filesModified: [], error: `Exceeded max turns (${maxTurns})` };
  }

  // ═══ Layer 2: runTurn — 单轮对话 + 模型降级 ═══
  private async runTurn(
    systemPrompt: string,
    messages: Message[],
  ): Promise<TurnResult> {
    const trimmedMessages = this.trimContext(messages);
    const models = [this.config.model.primary, ...(this.config.model.fallback ?? [])];

    for (const model of models) {
      try {
        return await this.runAttempt(model, systemPrompt, trimmedMessages);
      } catch (err) {
        if (this.isRetryable(err) && model !== models.at(-1)) {
          continue;
        }
        throw err;
      }
    }
    throw new Error('All models exhausted');
  }

  // ═══ Layer 3: runAttempt — 单次 LLM 调用 + 工具执行 ═══
  private async runAttempt(
    model: ModelRef,
    systemPrompt: string,
    messages: Message[],
  ): Promise<TurnResult> {
    // 1. 调用 LLM API
    const response = await this.modelProvider.chat({
      model: model.model,
      provider: model.provider,
      system: systemPrompt,
      messages,
      tools: this.toolRegistry.getToolDefinitions(),
      maxTokens: this.config.model.maxTokens,
    });

    // 2. 解析响应中的 tool_use blocks
    const toolCalls = response.content.filter(b => b.type === 'tool_use');
    const newMessages: Message[] = [{ role: 'assistant', content: response.content }];

    if (toolCalls.length === 0) {
      const finalText = response.content.filter(b => b.type === 'text').map(b => b.text).join('');
      return { newMessages, hasToolCalls: false, finalText };
    }

    // 3. 依次执行每个工具调用
    const toolResults: ToolResultBlock[] = [];
    for (const call of toolCalls) {
      const result = await this.toolRegistry.execute(call.name, call.input);
      toolResults.push({
        type: 'tool_result',
        tool_use_id: call.id,
        content: result.output,
        is_error: result.isError,
      });
    }

    newMessages.push({ role: 'user', content: toolResults });
    return { newMessages, hasToolCalls: true, finalText: '' };
  }
}
```

#### OpenClaw 管线 vs Overseer 管线对照

| 层级 | OpenClaw | Overseer Agent Runtime |
|------|----------|----------------------|
| **最外层** | `runReplyAgent()` — 管理整个回复周期 | `runTask()` — 管理整个任务周期 |
| **中间层** | `runAgentTurnWithFallback()` — 模型降级 | `runTurn()` — 模型降级 + token 管理 |
| **最内层** | `runEmbeddedAttempt()` — 单次 API 调用 + tool_use 解析 | `runAttempt()` — 单次 API 调用 + tool_use 解析 |
| **去掉的** | `runEmbeddedPiAgent()` — auth profile 轮转 | 无需（单 API Key） |

### 工具注册表

```typescript
// tools/registry.ts
class ToolRegistry {
  private tools: Map<string, Tool> = new Map();

  register(tool: Tool): void { this.tools.set(tool.name, tool); }

  getToolDefinitions(): ToolDefinition[] {
    return [...this.tools.values()].map(t => ({
      name: t.name,
      description: t.description,
      input_schema: t.inputSchema,
    }));
  }

  async execute(name: string, input: unknown): Promise<ToolOutput> {
    const tool = this.tools.get(name);
    if (!tool) return { output: `Unknown tool: ${name}`, isError: true };
    return tool.execute(input);
  }
}

// 内置工具
const tools: Tool[] = [
  // ── 工作区管理 ──
  new WorktreeCreateTool(),       // git worktree add → 返回工作区路径
  new WorktreeCleanupTool(),      // git worktree remove → 清理工作区

  // ── 文件操作 ──
  new FileReadTool(),             // 读文件
  new FileWriteTool(),            // 写文件
  new FileSearchTool(),           // grep / glob 搜索

  // ── 执行 ──
  new ShellExecTool(),            // 执行 shell 命令

  // ── Git / GitHub ──
  new GitOpsTool(),               // git add/commit/diff/log
  new GitPushTool(),              // git push
  new GitHubPRTool(),             // 创建 PR

  // ── 记忆 ──
  new MemoryReadTool(),           // 读取跨任务积累的项目知识
  new MemoryExtractTool(),        // 从对话历史中结构化提取经验记忆并保存

  // ── 子任务委托 ──
  new ClaudeCodeTool(),           // 委托子任务给 Claude Code CLI
];
```

#### MemoryReadTool — 读取经验记忆（Agent 工具）

Agent 在任务执行过程中通过 `memory_read` 读取已有项目知识：

```typescript
class MemoryReadTool implements Tool {
  name = 'memory_read';
  description = '读取之前任务积累的项目知识。可按类别过滤，也可读取全部。';
  inputSchema = {
    type: 'object',
    properties: {
      category: {
        type: 'string',
        enum: ['project_structure', 'conventions', 'lessons_learned', 'tool_usage'],
        description: '按类别过滤（可选，不传则返回全部）',
      },
    },
  };

  async execute(input: { category?: string }): Promise<ToolOutput> {
    const entries = input.category
      ? await memoryRepo.getByCategory(input.category)
      : await memoryRepo.getAll();

    if (entries.length === 0) {
      return { output: '暂无已知项目知识。', isError: false };
    }

    const formatted = entries
      .map(e => `[${e.category}] ${e.key}: ${e.value}`)
      .join('\n');
    return { output: formatted, isError: false };
  }
}
```

#### MemoryExtractTool — 结构化提取经验记忆（Agent 工具）

Agent 在任务收尾时调用 `memory_extract`，工具内部完成 **对话摘要 → LLM 结构化提取 → 批量写入**。

与逐条 `memory_write` 的区别：Agent 不需要自己判断"什么值得记"，
只需在收尾时调用一次 `memory_extract`，由工具内部的提取 prompt 保证质量。

```typescript
class MemoryExtractTool implements Tool {
  name = 'memory_extract';
  description = '从当前任务的执行历史中，结构化提取可复用的项目知识并保存。在任务收尾时调用一次即可。';
  inputSchema = {
    type: 'object',
    properties: {
      conversation_summary: {
        type: 'string',
        description: '当前任务的执行摘要（关键发现、踩过的坑、项目结构信息等）',
      },
    },
    required: ['conversation_summary'],
  };

  async execute(
    input: { conversation_summary: string },
    context: ToolContext,
  ): Promise<ToolOutput> {
    const extractionPrompt = `
分析以下 Agent 执行摘要，提取可复用的项目知识。

只提取以下 4 类信息，忽略任务特定的细节：

1. project_structure — 项目结构发现
   例: entry_file=src/index.ts, orm=drizzle, router=src/server/routes/

2. conventions — 项目约定
   例: package_manager=pnpm, test_framework=vitest, code_style=单引号+2空格

3. lessons_learned — 踩过的坑
   例: 不要用 npm（会报错）, 数据库迁移必须先执行 seed

4. tool_usage — 工具/命令用法
   例: build_command=pnpm run build, dev_command=pnpm dev

规则：
- 只输出对【未来任务】有复用价值的知识
- 如果没有新发现，返回空数组
- 每条 value 不超过 100 字

输出 JSON 数组：
[{ "category": "...", "key": "...", "value": "..." }]
`;

    const result = await context.modelProvider.chat({
      model: context.config.model.primary,
      messages: [
        { role: 'user', content: extractionPrompt + '\n\n' + input.conversation_summary }
      ],
      maxTokens: 1024,
    });

    const entries = JSON.parse(extractJsonFromResponse(result));
    let saved = 0;
    for (const entry of entries) {
      await memoryRepo.upsert({ ...entry, source: context.taskId });
      saved++;
    }

    return {
      output: saved > 0
        ? `已提取并保存 ${saved} 条项目知识:\n${entries.map((e: any) => `  [${e.category}] ${e.key}: ${e.value}`).join('\n')}`
        : '未发现新的可复用项目知识。',
      isError: false,
    };
  }
}
```

#### ClaudeCodeTool — 子任务委托工具

`claude_code` 不是运行时，是工具。Agent 可以把一个明确的子任务委托给它：

```typescript
class ClaudeCodeTool implements Tool {
  name = 'claude_code';
  description = '委托一个子任务给 Claude Code CLI 执行。适合需要完整 IDE 能力的独立子任务。';
  inputSchema = {
    type: 'object',
    properties: {
      prompt: { type: 'string', description: '子任务描述' },
      cwd: { type: 'string', description: '执行目录（通常是 worktree 路径）' },
      maxTurns: { type: 'number', description: '最大对话轮次', default: 30 },
    },
    required: ['prompt', 'cwd'],
  };

  async execute(input: { prompt: string; cwd: string; maxTurns?: number }): Promise<ToolOutput> {
    const result = await spawn('claude', [
      '--print',
      '--output-format', 'json',
      '--max-turns', String(input.maxTurns ?? 30),
      input.prompt,
    ], { cwd: input.cwd });

    return { output: parseClaudeOutput(result), isError: false };
  }
}
```

### Runner 中的调度逻辑

Runner 只做**调用 Agent Runtime + 状态更新**，不介入 Agent 的执行过程。
没有 backend 选择，没有环境准备。Agent 管一切。

```typescript
// engine/runner.ts

class Runner {
  private agent: AgentRuntime;

  constructor(config: Config) {
    this.agent = new AgentRuntime(config);
  }

  async runTask(task: AgentTask, issue: Issue): Promise<void> {
    // 1. 执行 — Agent 内部完成所有事情:
    //    memory_read → 加载已有项目知识
    //    创建 worktree → 写代码 → git commit → git push → 创建 PR → 清理 worktree
    //    收尾阶段调用 memory_extract → 结构化提取经验记忆
    //    可能还会调用 claude_code 工具委托子任务
    const result = await this.agent.run({ task, issue });

    // 2. Runner 只做状态更新
    if (result.success) {
      await taskRepo.complete(task.id, result);
      await issueRepo.updateStatus(issue.id, 'in_review');
    } else {
      await taskRepo.fail(task.id, result.error);
    }
  }
}
```

**关键简化**：
- 无 WebSocket，无认证，无热重载
- 1 Issue = 1 Agent Task（不做拆分、不做依赖 DAG）
- **单一 Agent Runtime**，没有可插拔 backend。claude_code 是工具，不是运行时
- **Agent 管一切**：worktree 创建/清理、git push、PR 创建全是工具，由 LLM 自己决定何时调用
- Runner 超薄：只调 `agent.run()` + 更新数据库状态

---

## 3. 数据模型

### 3.1 核心实体 (4 个表)

```typescript
interface Issue {
  id: string;               // ULID
  title: string;
  description: string;      // Markdown
  type: 'feature' | 'bugfix' | 'refactor' | 'docs';
  status: 'open' | 'ai_assigned' | 'in_progress' | 'in_review' | 'done' | 'failed';
  agentTaskId?: string;     // 1:1 关联（MVP 不做拆分）
  pullRequestUrl?: string;
  createdAt: Date;
  updatedAt: Date;
}

interface AgentTask {
  id: string;
  issueId: string;
  status: 'queued' | 'executing' | 'completed' | 'failed';
  retryCount: number;
  maxRetries: number;       // 默认 3
  branchName?: string;
  result?: {
    summary: string;
    filesModified: string[];
  };
  errorMessage?: string;
  createdAt: Date;
  completedAt?: Date;
}

interface Execution {
  id: string;
  taskId: string;
  attemptNumber: number;
  status: 'running' | 'completed' | 'failed';
  modelUsed: string;
  tokenUsage: { prompt: number; completion: number };
  toolCalls: ToolCallRecord[];   // JSON
  errorMessage?: string;
  startedAt: Date;
  finishedAt?: Date;
  durationMs?: number;
}

interface MemoryEntry {
  id: string;
  category: 'project_structure' | 'conventions' | 'lessons_learned' | 'tool_usage';
  key: string;                    // 如 "package_manager", "test_framework"
  value: string;                  // 如 "pnpm", "vitest"
  source: string;                 // 产生该记忆的 task ID
  createdAt: Date;
}
```

**Memory 说明**：轻量级 KV 记忆，用于跨任务积累项目知识。Agent 通过 `memory_read`
工具读取历史经验；在任务收尾阶段通过 `memory_extract` 工具从对话历史中结构化提取新知识
并写入。提取逻辑封装在工具内部（独立 LLM 调用 + 明确的提取规则），Agent 只需调用一次，
无需自己判断"什么值得记"。同一 `(category, key)` 只保留最新值，避免记忆膨胀。

典型记忆条目示例：
- `[project_structure] entry_file` → `src/index.ts`
- `[conventions] package_manager` → `pnpm`
- `[conventions] test_framework` → `vitest, 测试文件命名 *.test.ts`
- `[lessons_learned] npm_not_working` → `本项目使用 pnpm，不要用 npm`
- `[tool_usage] build_command` → `pnpm run build`

### 3.2 SQLite DDL

```sql
CREATE TABLE issues (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT 'feature'
    CHECK(type IN ('feature','bugfix','refactor','docs')),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','ai_assigned','in_progress','in_review','done','failed')),
  agent_task_id TEXT,
  pull_request_url TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE agent_tasks (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL REFERENCES issues(id),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK(status IN ('queued','executing','completed','failed')),
  retry_count INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  branch_name TEXT,
  result TEXT,               -- JSON
  error_message TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE executions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES agent_tasks(id),
  attempt_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK(status IN ('running','completed','failed')),
  model_used TEXT,
  token_usage TEXT DEFAULT '{}',
  tool_calls TEXT DEFAULT '[]',
  error_message TEXT,
  started_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT,
  duration_ms INTEGER
);

CREATE TABLE memory (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL
    CHECK(category IN ('project_structure','conventions','lessons_learned','tool_usage')),
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT,                   -- 产生该记忆的 task ID
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(category, key)          -- 同一类别同一 key 只保留最新值
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_tasks_status ON agent_tasks(status);
CREATE INDEX idx_tasks_issue ON agent_tasks(issue_id);
CREATE INDEX idx_exec_task ON executions(task_id);
CREATE INDEX idx_memory_category ON memory(category);
```

---

## 4. 核心流程

### 4.1 主流程 (MVP 极简)

```
 Human                  Server             Issue Service     Task Queue      Agent              GitHub
   │                      │                     │               │              │                   │
   │── POST /issues ─────▶│── create ──────────▶│               │              │                   │
   │◀── 201 {issue} ─────│                     │               │              │                   │
   │                      │                     │               │              │                   │
   │── POST /issues/:id  │                     │               │              │                   │
   │   /assign-ai ───────▶│── convert ─────────▶│── enqueue ───▶│              │                   │
   │◀── 200 {task} ──────│                     │               │              │                   │
   │                      │                     │               │              │                   │
   │                      │                     │    ┌── poll ──┤              │                   │
   │                      │                     │    └────┬─────┤              │                   │
   │                      │                     │         │────▶│─ runTask() ─▶│                   │
   │                      │                     │         │     │              │                   │
   │                      │                     │         │     │  Agent 自己管一切:                │
   │                      │                     │         │     │  memory_read (加载已有知识)       │
   │                      │                     │         │     │  → worktree_create               │
   │                      │                     │         │     │  → 写代码 (file_write)           │
   │                      │                     │         │     │  → git commit                    │
   │                      │                     │         │     │  → git push ─▶│── create PR ────▶│
   │                      │                     │         │     │  → worktree_cleanup              │
   │                      │                     │         │     │  → memory_extract (提取经验记忆)  │
   │                      │                     │         │     │              │                   │
   │                      │                     │◀─ done ─│◀────│              │                   │
   │                      │                     │ status:  │     │              │                   │
   │                      │                     │ in_review│     │              │                   │
   │                      │                     │         │     │              │                   │
   │── GET /issues/:id ──▶│── read ────────────▶│  (轮询查状态)  │              │                   │
   │◀── {status:in_review}│                     │               │              │                   │
   │                      │                     │               │              │                   │
   │── POST /issues/:id  │                     │               │              │                   │
   │   /approve ─────────▶│── close ───────────▶│               │              │── merge PR ──────▶│
   │◀── 200 ─────────────│                     │               │              │                   │
```

### 4.2 失败处理 (极简)

```
Agent 执行失败
    │
    ├── retryCount < maxRetries?
    │   ├── 是 → retryCount++, 重新入队
    │   └── 否 → Task 标记 failed, Issue 标记 failed
    │
    └── 人类：
        ├── PATCH /issues/:id 修改描述后重新 assign-ai
        └── 或放弃
```

---

## 5. REST API (MVP)

```
Issues:
  POST   /api/issues              创建 Issue
  GET    /api/issues              列出所有 Issue (可选 ?status=open)
  GET    /api/issues/:id          获取 Issue 详情 (含关联 Task 状态)
  PATCH  /api/issues/:id          更新 Issue (title/description/type)
  POST   /api/issues/:id/assign-ai   分配给 AI (触发转换 + 入队)
  POST   /api/issues/:id/approve     审查通过 (merge PR + 关闭)
  POST   /api/issues/:id/reject      审查不通过 (回到 open)

Agent Tasks (只读):
  GET    /api/tasks               列出所有 Task
  GET    /api/tasks/:id           获取 Task 详情 (含 Execution 历史)
  POST   /api/tasks/:id/cancel    取消执行中的 Task

System:
  GET    /api/health              健康检查
  GET    /api/status              Agent Runtime 状态 (当前任务、工具使用统计)
```

---

## 6. 配置 (MVP 极简)

```json5
// overseer.config.json5
{
  port: 18800,

  agent: {
    model: {
      primary: { provider: "anthropic", model: "claude-sonnet-4-20250514" },
      fallback: [                  // 模型降级链
        { provider: "openai", model: "gpt-4o" },
      ],
      maxTokens: 8192,
      temperature: 0,
    },
    maxTurns: 50,                  // Agent 循环最大轮次
    tools: [
      "worktree_create", "worktree_cleanup",
      "file_read", "file_write", "file_search",
      "shell_exec", "git_ops", "git_push", "github_pr",
      "memory_read", "memory_extract",     // 任务级经验记忆
      "claude_code",               // 子任务委托工具
    ],
    systemPrompt: "You are an expert software engineer...",

    // claude_code 工具配置
    claudeCode: {
      command: "claude",             // CLI 路径，默认从 PATH 查找
      maxTurns: 30,                  // 子任务最大对话轮次
    },
  },

  // 模型提供者
  models: {
    anthropic: {
      apiKey: "$ANTHROPIC_API_KEY",
    },
    openai: {
      apiKey: "$OPENAI_API_KEY",
    },
  },

  github: {
    token: "$GITHUB_TOKEN",
    repo: "owner/repo",
  },

  scheduler: {
    pollInterval: 5000,
    maxRetries: 3,
    timeoutMinutes: 30,
  },

  database: "./data/overseer.db",
}
```

不做 Zod 验证（MVP），启动时简单校验必填字段即可。

---

## 7. 目录结构 (MVP 扁平化)

```
claude-overseer/
├── package.json
├── tsconfig.json
├── overseer.config.json5
│
├── src/
│   ├── index.ts                 # 入口：启动 HTTP server + scheduler
│   │
│   ├── server/                  # HTTP 层
│   │   ├── app.ts               # Hono/Fastify app 实例
│   │   └── routes/
│   │       ├── issues.ts        # /api/issues/* 路由
│   │       ├── tasks.ts         # /api/tasks/* 路由 (只读)
│   │       └── system.ts        # /api/health, /api/agents
│   │
│   ├── issue/                   # LAYER 1
│   │   ├── issue.service.ts     # Issue CRUD + 状态机
│   │   └── converter.ts         # Issue → AgentTask (1:1)
│   │
│   ├── engine/                  # LAYER 2: 调度
│   │   ├── queue.ts             # 内存优先级队列 + SQLite 持久化
│   │   ├── scheduler.ts         # 轮询调度器
│   │   └── runner.ts            # runTask(): 调 AgentRuntime → 更新状态 (超薄)
│   │
│   ├── agent/                   # Agent Runtime (唯一的运行时)
│   │   ├── runtime.ts           # AgentRuntime: runTask → runTurn → runAttempt
│   │   └── model-provider.ts    # LLM API 统一调用层 (Anthropic/OpenAI/...)
│   │
│   ├── tools/                   # 工具注册表 + 所有工具
│   │   ├── registry.ts          # 工具注册 + 调度
│   │   ├── worktree-create.ts   # git worktree add
│   │   ├── worktree-cleanup.ts  # git worktree remove
│   │   ├── file-read.ts
│   │   ├── file-write.ts
│   │   ├── file-search.ts
│   │   ├── shell-exec.ts
│   │   ├── git-ops.ts
│   │   ├── git-push.ts
│   │   ├── github-pr.ts
│   │   ├── memory-read.ts         # 读取跨任务积累的项目知识
│   │   ├── memory-extract.ts      # 结构化提取经验记忆并保存
│   │   └── claude-code.ts       # 委托子任务给 Claude Code CLI
│   │
│   └── db/                      # 数据库
│       ├── connection.ts        # SQLite 连接 (better-sqlite3)
│       ├── migrations/          # SQL 迁移
│       └── repos/
│           ├── issue.repo.ts
│           ├── task.repo.ts
│           ├── execution.repo.ts
│           └── memory.repo.ts
│
└── test/
    ├── issue.test.ts
    ├── converter.test.ts
    ├── queue.test.ts
    ├── runtime.test.ts
    ├── tools.test.ts
    └── runner.test.ts
```

**关键简化**：不再是 monorepo，单 package 扁平结构。

---

## 8. ROADMAP

### MVP (v0.1) — 当前目标

**目标**：能跑通一条完整链路：创建 Issue → Agent 写代码 → 创建 PR

- [ ] HTTP Server + REST API (Issue CRUD)
- [ ] SQLite 存储 (4 张表: issues, agent_tasks, executions, memory)
- [ ] Issue → AgentTask 转换 (1:1)
- [ ] 内存任务队列 + 轮询调度器
- [ ] Agent Runtime (唯一运行时: runTask → runTurn → runAttempt)
- [ ] 内置工具 (worktree_create/cleanup, file_read/write/search, shell_exec, git_ops, git_push, github_pr, memory_read/extract, claude_code)
- [ ] Memory — 任务级经验记忆 (KV 存储，memory_read + memory_extract 工具，Agent 自主调用)
- [ ] ModelProvider 统一 LLM 调用层 (Anthropic API)
- [ ] Runner: 调 Agent Runtime → 更新状态 (超薄)
- [ ] 失败重试 (简单 retryCount)

### v0.2 — 可用性

- [ ] Web UI (React, Issue 列表 + 详情页 + Agent 日志)
- [ ] SSE 实时推送 (替代轮询)
- [ ] Zod 配置校验
- [ ] Issue 评论系统 (人工评论 + Agent 自动回写)
- [ ] ModelProvider 扩展 (OpenAI, Gemini)
- [ ] 模型降级 (primary → fallback)
- [ ] 标签 (Label) 过滤

### v1.0 — 完整单用户版

- [ ] JWT 认证
- [ ] WebSocket 实时日志流
- [ ] 1 Issue → N Task 拆分 + 依赖 DAG
- [ ] Milestone 里程碑
- [ ] 配置热重载
- [ ] FTS5 代码库全文索引 (升级 Memory 为向量化知识检索)
- [ ] 更多工具 (browser, test_runner)

### v2.0 — 多用户 / 生产级

- [ ] 多用户角色权限
- [ ] 审计日志 (AuditLog)
- [ ] 多仓库支持
- [ ] 通道扩展 (Telegram / Slack)
- [ ] 插件系统 (第三方工具注册)
- [ ] Docker 沙箱 (workspace 隔离升级，作为新 Agent 工具)
- [ ] Prometheus 指标
