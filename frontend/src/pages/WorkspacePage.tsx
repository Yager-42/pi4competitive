/* pi4 WorkspacePage —— SSE 工作台(精简版,Q5 事件映射)。
 * 不照搬 VerdaAI(依赖 VFlowDag/VAgentStream/VTracePanel/expertStore,pi4 无对应数据)。
 * 渲染:顶栏 + 阶段卡(plan/search/write)+ coverage 进度 + iteration + evidence 流 + sub-agent 节点。
 * done → 跳 /report/{reportId}(F2 实现 ReportPage 前,ReportPage 占位也可跳)。
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Sprout,
  ChevronLeft,
  FileText,
  CheckCircle2,
  Loader2,
  Search as SearchIcon,
  PenLine,
  Lightbulb,
  Square,
} from 'lucide-react'
import { useTaskStream } from '../hooks/useTaskStream'
import { useTaskStore } from '../store/taskStore'
import { abortTask } from '../lib/api'
import type { StageName } from '../types'

const STAGE_META: Record<StageName, { icon: typeof PenLine; label: string }> = {
  plan: { icon: Lightbulb, label: '规划' },
  search: { icon: SearchIcon, label: '搜索' },
  write: { icon: PenLine, label: '撰写' },
}

function stageColor(status: string): string {
  switch (status) {
    case 'running':
      return 'border-primary bg-primary-tint text-primary-deep'
    case 'ok':
      return 'border-ok bg-ok/10 text-ok'
    case 'failed':
      return 'border-risk bg-risk/10 text-risk'
    default:
      return 'border-line bg-card text-ink-3'
  }
}

export default function WorkspacePage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { state } = useLocation() as { state: { query?: string } | null }
  const query = state?.query ?? ''

  useTaskStream(taskId, query)

  const {
    stages,
    coverage,
    iteration,
    evidences,
    subagents,
    reportId,
    finished,
    error,
    running,
  } = useTaskStore()
  const [aborting, setAborting] = useState(false)

  async function onAbort() {
    if (!taskId || aborting) return
    const ok = window.confirm('确定中止此任务?\n\n研究将停止,后续阶段不再运行(可在列表恢复)。')
    if (!ok) return
    setAborting(true)
    await abortTask(taskId)
    // SSE 会推 error(status=aborted)或轮询兜底拿到 aborted;留工作台显示已中止
    setAborting(false)
  }

  useEffect(() => {
    if (finished && reportId) {
      const t = setTimeout(() => navigate(`/report/${reportId}`), 1600)
      return () => clearTimeout(t)
    }
  }, [finished, reportId, navigate])

  const ratio = coverage.ratio ?? (coverage.total ? coverage.filled / coverage.total : 0)

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button
          onClick={() => navigate('/')}
          className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 transition-colors hover:bg-primary-tint hover:text-primary-deep"
        >
          <ChevronLeft size={20} />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-btn bg-primary-tint text-primary">
          <Sprout size={18} strokeWidth={1.8} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">{query || '竞品分析任务'}</div>
          <div className="text-tag text-ink-3">任务 {taskId}</div>
        </div>
        <div className="hidden items-center gap-1.5 text-tag text-ink-2 sm:flex">
          <FileText size={13} /> {evidences.length} 条证据
        </div>
        {/* F4: 中止按钮(running 时显示) */}
        {running && !finished && !error && (
          <button
            onClick={onAbort}
            disabled={aborting}
            className="inline-flex items-center gap-1.5 rounded-btn bg-risk/10 px-3 h-9 text-aux font-medium text-risk hover:bg-risk/20 disabled:opacity-50"
          >
            {aborting ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} />} 中止
          </button>
        )}
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* 左:阶段 + coverage */}
        <div className="w-[340px] shrink-0 overflow-y-auto border-r border-line bg-card/50 p-5">
          <div className="text-tag font-semibold uppercase tracking-wider text-ink-3">阶段</div>
          <div className="mt-3 flex flex-col gap-3">
            {(Object.keys(STAGE_META) as StageName[]).map((name) => {
              const meta = STAGE_META[name]
              const status = stages[name]
              const Icon = meta.icon
              return (
                <div
                  key={name}
                  className={`flex items-center gap-3 rounded-card border-2 p-3 transition-all ${stageColor(status)}`}
                >
                  <Icon size={20} strokeWidth={1.8} />
                  <div className="min-w-0 flex-1">
                    <div className="text-aux font-medium">{meta.label}</div>
                    <div className="text-tag opacity-70">
                      {status === 'running' ? '进行中…' : status === 'ok' ? '完成' : status === 'failed' ? '失败' : '等待'}
                    </div>
                  </div>
                  {status === 'running' && <Loader2 size={18} className="animate-spin" />}
                  {status === 'ok' && <CheckCircle2 size={18} />}
                </div>
              )
            })}
          </div>

          <div className="mt-6 text-tag font-semibold uppercase tracking-wider text-ink-3">覆盖率</div>
          <div className="mt-3 rounded-card border border-line/60 bg-card p-4 shadow-card">
            <div className="flex items-center justify-between text-aux text-ink-2">
              <span>{coverage.filled} / {coverage.total} cell</span>
              <span className="font-medium text-primary-deep">{(ratio * 100).toFixed(0)}%</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-chip bg-line">
              <motion.div
                className="h-full rounded-chip bg-primary"
                animate={{ width: `${ratio * 100}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
            <div className="mt-2 flex justify-between text-tag text-ink-3">
              <span>unknown {coverage.unknown ?? 0}</span>
              <span>conflict {coverage.conflict ?? 0}</span>
              <span>轮次 {iteration}</span>
            </div>
          </div>
        </div>

        {/* 右:evidence 流 + sub-agent */}
        <div className="min-w-0 flex-1 overflow-y-auto p-5">
          <div className="text-tag font-semibold uppercase tracking-wider text-ink-3">搜索子任务</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {subagents.length === 0 && (
              <span className="text-aux text-ink-3">等待派发…</span>
            )}
            {subagents.map((n, i) => (
              <span
                key={`${n.entity}-${i}`}
                className={`inline-flex items-center gap-1.5 rounded-chip px-3 h-8 text-tag font-medium ${
                  n.status === 'running' ? 'bg-primary-tint text-primary-deep' : 'bg-ok/15 text-ok'
                }`}
              >
                {n.status === 'running' && <Loader2 size={12} className="animate-spin" />}
                {n.status === 'done' && <CheckCircle2 size={12} />}
                {n.entity}
              </span>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <div className="text-tag font-semibold uppercase tracking-wider text-ink-3">证据流</div>
            <span className="text-tag text-ink-3">{evidences.length} 条</span>
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {evidences.length === 0 && (
              <div className="rounded-card border border-line/60 bg-card p-4 text-aux text-ink-3">
                等待 judge 抽取证据…
              </div>
            )}
            {evidences.slice(-40).reverse().map((ev, i) => (
              <motion.div
                key={`${ev.evidence_id ?? ''}-${i}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-card border border-line/60 bg-card p-3 shadow-card"
              >
                <div className="flex items-center gap-2 text-tag text-ink-3">
                  <span className="font-medium text-ink-2">{ev.entity ?? '—'}</span>
                  <span>·</span>
                  <span>{ev.attribute ?? '—'}</span>
                  {ev.confidence != null && (
                    <span className="ml-auto rounded-chip bg-primary-tint px-2 text-tag text-primary-deep">
                      {(ev.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <div className="mt-1 text-aux text-ink">{ev.value || ev.finding || '—'}</div>
                {ev.source && <div className="mt-1 truncate text-tag text-ink-3">{ev.source}</div>}
              </motion.div>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="absolute bottom-6 right-6 rounded-card border border-risk/40 bg-card p-4 shadow-float">
          <div className="text-aux font-medium text-risk">{error}</div>
        </div>
      )}
    </div>
  )
}
