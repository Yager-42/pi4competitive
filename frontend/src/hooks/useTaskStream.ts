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
const STREAM_STALL_TIMEOUT = 20000
const WATCHDOG_INTERVAL = 5000


export function useTaskStream(taskId: string | undefined, query: string) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)
  const applyTask = useTaskStore((s) => s.applyTask)

  useEffect(() => {
    if (!taskId) return

    const controller = new AbortController()
    let active = true
    let pollTimer: number | null = null
    let watchdogTimer: number | null = null
    let pollInFlight = false
    let eventVersion = 0
    let httpGeneration = 0
    let lastEventAt = Date.now()
    let readFailures = 0

    const isCurrent = () => active && useTaskStore.getState().taskId === taskId
    const stopPolling = () => {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    }
    const stopWatchdog = () => {
      if (watchdogTimer !== null) {
        window.clearInterval(watchdogTimer)
        watchdogTimer = null
      }
    }
    const stopIfTerminal = () => {
      const state = useTaskStore.getState()
      if (state.finished || state.error) {
        stopPolling()
        stopWatchdog()
      }
    }

    reset(taskId, query)

    // Ignore a delayed initial HTTP snapshot once any newer SSE event or HTTP
    // request has advanced the local freshness sequence.
    const initialGeneration = ++httpGeneration
    const initialEventVersion = eventVersion
    void fetchTask(taskId, controller.signal)
      .then((t) => {
        if (!t) {
          if (isCurrent()) readFailures += 1
          return
        }
        if (
          isCurrent() &&
          initialGeneration === httpGeneration &&
          initialEventVersion === eventVersion
        ) {
          applyTask(t)
          stopIfTerminal()
        }
      })
      .catch((error) => {
        if (
          error &&
          typeof error === 'object' &&
          'name' in error &&
          error.name === 'AbortError'
        ) return
        if (isCurrent()) readFailures += 1
      })

    const poll = async () => {
      if (!isCurrent() || pollInFlight) return
      pollInFlight = true
      const requestGeneration = ++httpGeneration
      const requestEventVersion = eventVersion
      try {
        const t = await fetchTask(taskId, controller.signal)
        if (
          !isCurrent() ||
          requestGeneration !== httpGeneration ||
          requestEventVersion !== eventVersion
        ) return
        if (!t) {
          readFailures += 1
          if (readFailures >= 3) {
            ingest('error', { message: '任务状态加载失败，请稍后重试' })
            stopIfTerminal()
          }
          return
        }
        applyTask(t)
        readFailures = 0
        stopIfTerminal()
      } catch (error) {
        if (
          error &&
          typeof error === 'object' &&
          'name' in error &&
          error.name === 'AbortError'
        ) return
        if (!isCurrent()) return
        readFailures += 1
        if (readFailures >= 3) {
          ingest('error', { message: '任务状态加载失败，请稍后重试' })
          stopIfTerminal()
        }
      } finally {
        pollInFlight = false
      }
    }

    const startPolling = () => {
      if (!isCurrent() || pollTimer !== null) return
      void poll()
      pollTimer = window.setInterval(() => void poll(), POLL_INTERVAL)
    }

    // A connection can stay open while a proxy silently drops task events.
    // Heartbeats do not change task state, so this timer independently starts
    // the same polling fallback when no task event has arrived recently.
    watchdogTimer = window.setInterval(() => {
      if (!isCurrent()) return
      const state = useTaskStore.getState()
      if (state.finished || state.error) {
        stopIfTerminal()
      } else if (Date.now() - lastEventAt >= STREAM_STALL_TIMEOUT) {
        startPolling()
      }
    }, WATCHDOG_INTERVAL)

    const close = openTaskStream(taskId, {
      onEvent: (type, data) => {
        if (!isCurrent()) return
        eventVersion += 1
        lastEventAt = Date.now()
        readFailures = 0
        ingest(type, data)
        stopIfTerminal()
      },
      onOpen: () => {
        lastEventAt = Date.now()
      },
      onError: () => {
        if (!isCurrent()) return
        const state = useTaskStore.getState()
        if (state.finished || state.error) {
          stopIfTerminal()
          return
        }
        startPolling()
      },
    })

    return () => {
      active = false
      controller.abort()
      close()
      stopPolling()
      stopWatchdog()
    }
  }, [taskId, query, reset, ingest, applyTask])
}
