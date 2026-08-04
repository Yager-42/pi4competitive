/* pi4 任务 store —— 按 pi4 SSE 12 事件 ingest(Q5 映射)。
 * 砍 VerdaAI 的 thought/chart/image/progress/node_update/trace 事件分支(pi4 无对应)。
 */
import { create } from 'zustand'
import type {
  Coverage,
  Evidence,
  SSEEventType,
  StageName,
  StageStatus,
  SubagentNode,
  Task,
  TaskProjection,
} from '../types'

export interface TaskState {
  taskId: string | null
  query: string
  running: boolean
  finished: boolean
  reportId: string | null
  stages: Record<StageName, StageStatus>
  currentStage: StageName | null
  coverage: Coverage
  iteration: number
  evidences: Evidence[]
  subagents: SubagentNode[]
  error: string | null

  reset: (taskId: string, query: string) => void
  ingest: (type: SSEEventType, data: unknown) => void
  applyTask: (task: Task) => void
}

const INIT_STAGES: Record<StageName, StageStatus> = {
  plan: 'pending',
  search: 'pending',
  write: 'pending',
}

const initCoverage: Coverage = { filled: 0, total: 0, unknown: 0, conflict: 0, ratio: 0 }

/* SSE 下发的是动态 JSON,统一收敛成可索引对象再按字段断言 */
type LooseRecord = Record<string, unknown>
function asObj(d: unknown): LooseRecord {
  return (d ?? {}) as LooseRecord
}

export const useTaskStore = create<TaskState>((set, get) => ({
  taskId: null,
  query: '',
  running: false,
  finished: false,
  reportId: null,
  stages: { ...INIT_STAGES },
  currentStage: null,
  coverage: { ...initCoverage },
  iteration: 0,
  evidences: [],
  subagents: [],
  error: null,

  reset: (taskId, query) =>
    set({
      taskId,
      query,
      running: true,
      finished: false,
      reportId: null,
      stages: { ...INIT_STAGES },
      currentStage: null,
      coverage: { ...initCoverage },
      iteration: 0,
      evidences: [],
      subagents: [],
      error: null,
    }),

  ingest: (type, data) => {
    const d = asObj(data)
    const s = get()
    if (d.task_id != null && d.task_id !== s.taskId) return
    switch (type) {
      case 'state_snapshot': {
        const stages = d.stages as Record<string, string> | undefined
        const coverage = d.coverage as Coverage | undefined
        set({
          currentStage: (d.current_stage as StageName | null) ?? s.currentStage,
          stages: stages
            ? { plan: (stages.plan as StageStatus) ?? 'pending', search: (stages.search as StageStatus) ?? 'pending', write: (stages.write as StageStatus) ?? 'pending' }
            : s.stages,
          coverage: coverage ?? s.coverage,
          iteration: (d.iteration as number) ?? s.iteration,
        })
        return
      }
      case 'stage_start': {
        const stage = d.stage as StageName
        set({
          currentStage: stage,
          stages: stage ? { ...s.stages, [stage]: 'running' } : s.stages,
        })
        return
      }
      case 'stage_end': {
        const stage = d.stage as StageName
        const ok = d.ok !== false
        set({
          stages: stage ? { ...s.stages, [stage]: ok ? 'ok' : 'failed' } : s.stages,
        })
        return
      }
      case 'coverage_update': {
        set({ coverage: (d as unknown as Coverage) ?? s.coverage })
        return
      }
      case 'evidence': {
        set({ evidences: [...s.evidences, d as unknown as Evidence] })
        return
      }
      case 'subagent_start': {
        const entity = (d.entity as string) ?? (d.entity_id as string) ?? 'sub-agent'
        set({
          subagents: [
            ...s.subagents,
            { entity, status: 'running', started_at: Date.now() },
          ],
        })
        return
      }
      case 'subagent_end': {
        const entity = (d.entity as string) ?? (d.entity_id as string)
        set({
          subagents: s.subagents.map((n) =>
            entity && n.entity === entity ? { ...n, status: 'done' as const } : n,
          ),
        })
        return
      }
      case 'iteration_start': {
        set({ iteration: s.iteration + 1 })
        return
      }
      case 'report_ready': {
        set({ reportId: (d.report_id as string) ?? (d.task_id as string) ?? s.reportId })
        return
      }
      case 'done': {
        set({
          running: false,
          finished: true,
          reportId: (d.report_id as string) ?? (d.task_id as string) ?? s.reportId ?? s.taskId,
        })
        return
      }
      case 'error': {
        set({
          error: (d.message as string) ?? (d.status as string) ?? '任务出错',
          running: false,
        })
        return
      }
    }
  },

  /* F4: 从 GET /tasks/{id} 的 Task 填 store(进入先拉 + SSE 断连轮询兜底) */
  applyTask: (task: Task) => {
    const s = get()
    const proj: TaskProjection = task.projection || ({} as TaskProjection)
    const stagesIn = proj.stages || {}
    const stagePatch: Record<StageName, StageStatus> = {
      plan: (stagesIn.plan as StageStatus) ?? s.stages.plan,
      search: (stagesIn.search as StageStatus) ?? s.stages.search,
      write: (stagesIn.write as StageStatus) ?? s.stages.write,
    }
    const coverage = proj.coverage ?? s.coverage
    const current = (proj.current_stage as StageName | null) ?? s.currentStage
    const patch: Partial<TaskState> = {
      taskId: task.task_id,
      currentStage: current,
      stages: stagePatch,
      coverage,
    }
    const status = task.status
    if (status === 'completed') {
      patch.running = false
      patch.finished = true
      patch.reportId = task.task_id
    } else if (status === 'failed') {
      patch.running = false
      patch.error = '任务失败'
    } else if (status === 'aborted') {
      patch.running = false
      patch.error = '已中止'
    } else if (status === 'awaiting_clarify') {
      patch.running = false
    } else {
      // running / pending → keep running
      patch.running = true
    }
    set(patch)
  },
}))
