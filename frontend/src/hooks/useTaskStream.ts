/* 接入 pi4 任务 SSE 流 + GET /tasks/{id} 兜底(F4)。
 *
 * 流程:
 * 1. 进入先拉 GET /tasks/{id} → applyTask(避免 SSE 没推 snapshot 时白屏;若已终态直接显示)
 * 2. 开 SSE(reset → open → ingest)
 * 3. SSE 断连(onError)+ 未终态 → 切 5s 轮询 GET /tasks/{id} → applyTask,直到终态或卸载
 *
 * 不使用 startedRef 守卫,否则 StrictMode 卸载会关闭连接后无法重连(同 VerdaAI)。
 */
import { useEffect } from 'react'
import { openTaskStream, fetchTask } from '../lib/api'
import { useTaskStore } from '../store/taskStore'

const POLL_INTERVAL = 5000
const TERMINAL: Record<string, true> = { completed: true, failed: true, aborted: true }

export function useTaskStream(taskId: string | undefined, query: string) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)
  const applyTask = useTaskStore((s) => s.applyTask)

  useEffect(() => {
    if (!taskId) return

    const controller = new AbortController()
    let active = true
    let pollTimer: number | null = null
    let pollInFlight = false

    const isCurrent = () => active && useTaskStore.getState().taskId === taskId
    const stopPolling = () => {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    }

    reset(taskId, query)

    // 1. 进入先拉一次单任务状态(兜底白屏 + 终态直接显示)
    void fetchTask(taskId, controller.signal)
      .then((t) => {
        if (isCurrent() && t) applyTask(t)
      })
      .catch(() => {
        // SSE/polling remains the fallback for transient GET failures.
      })

    const startPolling = () => {
      if (!isCurrent() || pollTimer !== null) return
      pollTimer = window.setInterval(async () => {
        if (!isCurrent() || pollInFlight) return
        pollInFlight = true
        try {
          const t = await fetchTask(taskId, controller.signal)
          if (!isCurrent() || !t) return
          applyTask(t)
          if (TERMINAL[t.status]) stopPolling()
        } catch {
          // Keep polling after transient failures until the effect is cleaned up.
        } finally {
          pollInFlight = false
        }
      }, POLL_INTERVAL)
    }

    // 2. 开 SSE
    const close = openTaskStream(taskId, {
      onEvent: (type, data) => {
        if (isCurrent()) ingest(type, data)
      },
      onError: () => {
        // SSE 断连(含正常结束);仅未终态时切轮询
        if (!isCurrent()) return
        const st = useTaskStore.getState()
        if (st.finished || st.error) return
        startPolling()
      },
    })

    return () => {
      active = false
      controller.abort()
      close()
      stopPolling()
    }
  }, [taskId, query, reset, ingest, applyTask])
}
