/* pi4 前端类型定义 —— 前后端契约(snake_case,对齐 pi4 后端 v0.3.3) */

/* 澄清问卷(pi4 POST /tasks {query} 返的 questions[]) */
export interface ClarifyQuestion {
  id: string
  question: string
  hint?: string
  type: 'single' | 'multi' | 'text'
  options?: string[]
}

/* 任务创建返回(pi4 POST /api/v2/tasks) */
export interface CreateTaskResp {
  task_id: string
  status: 'awaiting_clarify' | 'pending'
  session_id?: string | null
  query?: string
  questions?: ClarifyQuestion[]
}

/* 澄清答案(POST /api/v2/tasks/{id}/clarify body) */
export interface ClarifyAnswer {
  id: string
  value: string | string[]
}

/* pi4 SSE 事件类型(12,span 不推 SSE——走 GET /trace) */
export type SSEEventType =
  | 'state_snapshot'
  | 'stage_start'
  | 'stage_end'
  | 'coverage_update'
  | 'evidence'
  | 'subagent_start'
  | 'subagent_end'
  | 'iteration_start'
  | 'report_ready'
  | 'done'
  | 'error'

/* 覆盖率四态(pi4 coverage projection) */
export interface Coverage {
  filled: number
  total: number
  unknown?: number
  conflict?: number
  ratio?: number
}

/* 阶段状态 */
export type StageStatus = 'pending' | 'running' | 'ok' | 'failed'
export type StageName = 'plan' | 'search' | 'write'

/* 证据(SSE evidence 事件 + GET /evidences items) */
export interface Evidence {
  evidence_id?: string
  entity?: string
  attribute?: string
  value?: string
  finding?: string
  source?: string
  source_url?: string
  source_type?: string
  domain?: string
  brand?: string
  confidence?: number
  captured_at?: string
}

/* sub-agent 节点(SSE subagent_start/end,替代 VerdaAI 专家节点) */
export interface SubagentNode {
  entity: string
  status: 'running' | 'done'
  started_at?: number
}
