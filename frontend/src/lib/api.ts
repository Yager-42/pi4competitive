/* pi4 前端 API 适配层 —— 直按 pi4 后端契约(/api/v2 + snake_case),后端不动。
 * dev 走 vite proxy(/api → 127.0.0.1:8010,API_BASE 空串);prod 用 VITE_API_BASE 指向后端。
 */
import type {
  ClarifyAnswer,
  CreateTaskResp,
  DashboardStats,
  EvidenceQueryResp,
  Report,
  ReportCard,
  SSEEventType,
  Subscription,
  TraceSpan,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function safeJson<T>(path: string, init?: RequestInit, fallback?: T): Promise<T> {
  try {
    const r = await fetch(`${API_BASE}${path}`, init)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return (await r.json()) as T
  } catch (e) {
    if (fallback !== undefined) return fallback
    throw e
  }
}

/* POST /api/v2/tasks {query} → {task_id, status, questions?} */
export async function createTask(query: string): Promise<CreateTaskResp> {
  return safeJson<CreateTaskResp>(
    '/api/v2/tasks',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    },
    { task_id: `demo-${Date.now()}`, status: 'pending' },
  )
}

/* POST /api/v2/tasks/{id}/clarify {answers} → 启动研究 */
export async function submitClarify(
  taskId: string,
  answers: ClarifyAnswer[],
): Promise<{ ok: boolean; status?: string }> {
  return safeJson(
    `/api/v2/tasks/${taskId}/clarify`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    },
    { ok: true },
  )
}

/* SSE:监听 pi4 任务流(12 事件),返回关闭函数 */
export interface SSEHandlers {
  onEvent: (type: SSEEventType, data: unknown) => void
  onError?: (e: unknown) => void
  onOpen?: () => void
}

export function openTaskStream(taskId: string, handlers: SSEHandlers): () => void {
  const url = `${API_BASE}/api/v2/tasks/${taskId}/stream`
  const es = new EventSource(url)
  const types: SSEEventType[] = [
    'state_snapshot',
    'stage_start',
    'stage_end',
    'coverage_update',
    'evidence',
    'subagent_start',
    'subagent_end',
    'iteration_start',
    'report_ready',
    'done',
    'error',
  ]
  es.onopen = () => handlers.onOpen?.()
  for (const t of types) {
    es.addEventListener(t, (ev) => {
      let parsed: unknown = (ev as MessageEvent).data
      try {
        parsed = JSON.parse((ev as MessageEvent).data)
      } catch {
        /* keep raw */
      }
      handlers.onEvent(t, parsed)
    })
  }
  es.onerror = (e) => {
    handlers.onError?.(e)
  }
  return () => es.close()
}

/* ============================================================ F2 报告闭环 */

/* GET /api/v2/reports → {reports: ReportCard[]} */
export async function fetchReports(): Promise<ReportCard[]> {
  return safeJson<{ reports: ReportCard[] }>('/api/v2/reports', undefined, { reports: [] })
    .then((r) => r.reports ?? [])
}

/* GET /api/v2/reports/{id} → Report 全文(refine 优先 write + coverage + coverage_map) */
export async function fetchReport(reportId: string): Promise<Report | null> {
  return safeJson<Report | null>(`/api/v2/reports/${reportId}`, undefined, null)
}

/* GET /api/v2/tasks/{id}/trace → {spans: TraceSpan[]} */
export async function fetchTrace(reportId: string): Promise<TraceSpan[]> {
  return safeJson<{ spans: TraceSpan[] }>(`/api/v2/tasks/${reportId}/trace`, undefined, { spans: [] })
    .then((r) => r.spans ?? [])
}

/* POST /api/v2/reports/{id}/refine {section_id, annotations[]} → section 级重写 */
export async function refineSection(
  reportId: string,
  sectionId: string,
  annotations: string[],
): Promise<{ ok: boolean; message?: string }> {
  return safeJson(
    `/api/v2/reports/${reportId}/refine`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: sectionId, annotations }),
    },
    { ok: false, message: '请求失败' },
  )
}

/* POST /api/v2/reports/{id}/feedback {edited_blocks, total_blocks, data?} → 修正率 */
export async function submitFeedback(
  reportId: string,
  editedBlocks: number,
  totalBlocks: number,
  data: Record<string, unknown> = {},
): Promise<{ ok: boolean; revision_rate?: number }> {
  return safeJson(
    `/api/v2/reports/${reportId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edited_blocks: editedBlocks, total_blocks: totalBlocks, data }),
    },
    { ok: true },
  )
}

/* ============================================================ F3 情报闭环 */

/* GET /api/v2/dashboard → DashboardStats(11 指标 + 分布) */
export async function fetchDashboard(): Promise<DashboardStats | null> {
  return safeJson<DashboardStats | null>('/api/v2/dashboard', undefined, null)
}

/* GET /api/v2/evidences?brand=&source_type=&min_confidence=&limit= → {items, facets} */
export async function fetchEvidences(params?: {
  brand?: string
  source_type?: string
  min_confidence?: number
  limit?: number
}): Promise<EvidenceQueryResp> {
  const qs = new URLSearchParams()
  if (params?.brand) qs.set('brand', params.brand)
  if (params?.source_type) qs.set('source_type', params.source_type)
  if (params?.min_confidence != null) qs.set('min_confidence', String(params.min_confidence))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return safeJson<EvidenceQueryResp>(`/api/v2/evidences${suffix}`, undefined, {
    items: [],
    facets: { total: 0, by_type: {}, by_brand: {} },
  })
}

/* GET /api/v2/subscriptions → {subscriptions: Subscription[]} */
export async function fetchSubscriptions(): Promise<Subscription[]> {
  return safeJson<{ subscriptions: Subscription[] }>('/api/v2/subscriptions', undefined, { subscriptions: [] })
    .then((r) => r.subscriptions ?? [])
}

/* POST /api/v2/subscriptions {query, brands} */
export async function createSubscription(query: string, brands: string[]): Promise<Subscription | null> {
  return safeJson<Subscription | null>(
    '/api/v2/subscriptions',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, brands }),
    },
    null,
  )
}

/* DELETE /api/v2/subscriptions/{sub_id} */
export async function deleteSubscription(subId: string): Promise<{ ok: boolean }> {
  return safeJson(`/api/v2/subscriptions/${subId}`, { method: 'DELETE' }, { ok: true })
}

/* POST /api/v2/subscriptions/{sub_id}/run → {ok, task_id, status} */
export async function runSubscription(subId: string): Promise<{ ok: boolean; task_id?: string; status?: string }> {
  return safeJson(`/api/v2/subscriptions/${subId}/run`, { method: 'POST' }, { ok: false })
}

export { API_BASE }
