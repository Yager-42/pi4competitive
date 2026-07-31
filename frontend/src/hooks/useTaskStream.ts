/* 接入 pi4 任务 SSE 流 + GET /tasks/{id} 兜底(F4)。
 *
 * 流程:
 * 1. 进入先拉 GET /tasks/{id} → applyTask(避免 SSE 没推 snapshot 时白屏;若已终态直接显示)
 * 2. 开 SSE(reset → open → ingest)
 * 3. SSE 断连(onError)+ 未终态 → 切 5s 轮询 GET /tasks/{id} → applyTask,直到终态或卸载
 *
 * 不使用 startedRef 守卫,否则 StrictMode 卸载会关闭连接后无法重连(同 VerdaAI)。
 */
import { useEffect, useRef } from 'react'
import { openTaskStream, fetchTask } from '../lib/api'
import { useTaskStore } from '../store/taskStore'

const POLL_INTERVAL = 5000
const TERMINAL = new Set(['completed', 'failed', 'aborted'])

export function useTaskStream(taskId: string | undefined, query: string) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)
  const applyTask = useTaskStore((s) => s.applyTask)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!taskId) return

    reset(taskId, query)

    // 1. 进入先拉一次单任务状态(兜底白屏 + 终态直接显示)
    fetchTask(taskId).then((t) => {
      if (t) applyTask(t)
    })

    // 2. 开 SSE
    let sseClosed = false
    const close = openTaskStream(taskId, {
      onEvent: (type, data) => ingest(type, data),
      onError: () => {
        // SSE 断连(含正常结束);仅未终态时切轮询
        if (sseClosed) return
        const st = useTaskStore.getState()
        if (st.finished || st.error) return
        if (pollTimer.current) return
        pollTimer.current = setInterval(async () => {
          const t = await fetchTask(taskId)
          if (!t) return
          applyTask(t)
          if (TERMINAL.has(t.status)) {
            if (pollTimer.current) {
              clearInterval(pollTimer.current)
              pollTimer.current = null
            }
          }
        }, POLL_INTERVAL)
      },
    })

    return () => {
      sseClosed = true
      close()
      if (pollTimer.current) {
        clearInterval(pollTimer.current)
        pollTimer.current = null
      }
    }
  }, [taskId, query, reset, ingest, applyTask])
}
