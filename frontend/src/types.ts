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

/* v0.3.5: per-task 搜索超参覆盖(全可选,空=用默认) */
export interface SearchOverrides {
  max_parallel?: number | string  // 1-16,默认 4
  coverage_threshold?: number | string  // 0.05-1.0,默认 0.8
  max_queries?: number | string  // 1-200,默认 40
  max_wall_seconds?: number | string  // 30-3600,默认 600
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

/* 证据: SSE/internal graph uses source; GET /api/v2/evidences uses source_url. */
export interface Evidence {
  evidence_id?: string
  entity?: string
  attribute?: string
  value?: string
  finding?: string
  /** Source identifier emitted by SSE and coverage graph projections. */
  source?: string
  /** Canonical URL field returned by the evidence-list API. */
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

/* ============================================================ F2 报告闭环 */

/* 报告卡片(GET /api/v2/reports 返 {reports: ReportCard[]}) */
export interface ReportCard {
  report_id: string
  title: string
  brands: string[]
  evidence_count: number
  claim_count: number
  coverage_ratio: number
  status: string
  created_at: string
}

/* 报告章节(POST /reports/{id}/refine 重写后标 refined) */
export interface ReportSection {
  id: string
  title: string
  body: string
  refined?: boolean
}

/* 报告全文(GET /api/v2/reports/{id}) */
export interface Report {
  ok: boolean
  report_id?: string
  title?: string
  markdown?: string
  sections?: ReportSection[]
  coverage?: Coverage
  coverage_map?: CoverageMatrix
  evidence_count?: number
  sources?: string[]
  created_at?: string
  message?: string
  status?: string
}

/* coverage_map 矩阵(GET /reports/{id} 补字段,F2 后端补) */
export interface CoverageMatrixCell {
  entity_id: string
  attribute_id: string
  status: 'filled' | 'empty' | 'unknown' | 'conflict'
  value?: string
  source?: string
  source_excerpt?: string
  confidence?: number
  attempts?: number
  candidates?: { value: string; source: string; confidence: number }[]
}

export interface CoverageMatrixEntity {
  id: string
  name: string
  kind?: string
}

export interface CoverageMatrixAttribute {
  id: string
  name: string
  dimension?: string
  type?: string
}

export interface CoverageMatrix {
  entities: CoverageMatrixEntity[]
  attributes: CoverageMatrixAttribute[]
  cells: CoverageMatrixCell[]
}

/* trace span(GET /api/v2/tasks/{id}/trace)——轻量,无 prompt/response 全文 */
export interface TraceSpan {
  span_id: string
  task_id: string
  seq: number
  kind: 'plan' | 'subagent' | 'judge' | 'write' | string
  stage?: string | null
  entity?: string | null
  model?: string | null
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  ts: string
}

/* ============================================================ F3 情报闭环 */

/* 仪表盘统计(GET /api/v2/dashboard) */
export interface DashboardStats {
  reports: number
  tasks_total: number
  tasks_by_status: Record<string, number>
  evidence_total: number
  claim_total: number
  high_conf_total: number
  avg_evidence_per_report: number
  avg_coverage: number
  fact_accuracy: number
  token_total: number
  brand_distribution: Record<string, number>
  source_type_distribution: Record<string, number>
}

/* 订阅(GET/POST /api/v2/subscriptions) */
export interface Subscription {
  sub_id: string
  query: string
  brands: string[]
  interval_hours: number
  created_at: string
  last_run_at: string | null
  last_task_id: string | null
  run_count: number
}

/* 证据库查询(GET /api/v2/evidences) */
export interface EvidenceQueryResp {
  items: Evidence[]
  facets: {
    total: number
    by_type: Record<string, number>
    by_brand: Record<string, number>
  }
}

/* ============================================================ F4 补缺口 */

/* 任务(GET /tasks 全量 / GET /tasks/{id} 单任务) */
export interface TaskProjection {
  current_stage: string | null
  stages: Record<string, string>
  coverage: Coverage
  report_title?: string
  brands?: string[]
  evidence_count?: number
  claim_count?: number
}

export interface Task {
  task_id: string
  session_id: string | null
  query: string
  status: string
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
  projection: TaskProjection
}



