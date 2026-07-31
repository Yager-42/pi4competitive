/* pi4 前端 API 适配层 —— 直按 pi4 后端契约(/api/v2 + snake_case),后端不动。
 * dev 走 vite proxy(/api → 127.0.0.1:8010,API_BASE 空串);prod 用 VITE_API_BASE 指向后端。
 */
import type {
  ClarifyAnswer,
  CreateTaskResp,
  SSEEventType,
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

export { API_BASE }
