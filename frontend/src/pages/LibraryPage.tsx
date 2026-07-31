/* pi4 LibraryPage —— 全量任务列表(F4 改造:GET /tasks 替代 GET /reports)。
 * 卡片按 status 分行为:completed→报告 / running&awaiting→进度 / failed&aborted→恢复;全状态删除。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, Clock, Network, Trash2, Play, RotateCcw, Loader2 } from 'lucide-react'
import { fetchTasks, resumeTask, deleteTask } from '../lib/api'
import type { Task } from '../types'
import { fadeUp, stagger } from '../lib/motion'

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-ok/15 text-ok',
  failed: 'bg-risk/15 text-risk',
  aborted: 'bg-risk/15 text-risk',
  running: 'bg-primary/15 text-primary',
  awaiting_clarify: 'bg-info/15 text-info',
  pending: 'bg-warn/15 text-warn',
}
const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  aborted: '已中止',
  running: '运行中',
  awaiting_clarify: '待澄清',
  pending: '等待',
}

export default function LibraryPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [resuming, setResuming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    const t = await fetchTasks()
    setTasks(t)
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  async function onResume(t: Task) {
    if (resuming) return
    setResuming(t.task_id)
    const r = await resumeTask(t.task_id)
    // completed → 不跳(running→409 在 safeJson 走 fallback,这里简化处理)
    if (r.status === 'pending' || r.status === 'running') {
      navigate(`/workspace/${t.task_id}`, { state: { query: t.query } })
    }
    setResuming(null)
  }

  async function onDelete(t: Task) {
    const ok = window.confirm(
      `确定删除任务?\n\n查询:${t.query}\n状态:${STATUS_LABEL[t.status] ?? t.status}\n\n将删除任务及其关联 session / SOCM / 证据,不可恢复。`,
    )
    if (!ok) return
    setDeleting(t.task_id)
    await deleteTask(t.task_id)
    setDeleting(null)
    await load()
  }

  function openTask(t: Task) {
    if (t.status === 'completed') navigate(`/report/${t.task_id}`)
    else if (t.status === 'running' || t.status === 'awaiting_clarify') {
      navigate(`/workspace/${t.task_id}`, { state: { query: t.query } })
    }
  }

  return (
    <div className="mx-auto max-w-content px-8 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-h1 text-ink">我的调研</h1>
          <p className="mt-1 text-aux text-ink-2">全量任务(含失败 / 中止 / 运行中)</p>
        </div>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-1.5 rounded-btn bg-primary px-4 h-10 text-aux font-medium text-white hover:bg-primary-deep"
        >
          <Play size={15} /> 新建调研
        </button>
      </div>

      {loading ? (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="v-skeleton h-44 rounded-card" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="mt-12 flex flex-col items-center text-ink-3">
          <FileText size={48} strokeWidth={1.2} />
          <p className="mt-4 text-aux">还没有任务</p>
          <button onClick={() => navigate('/')} className="mt-4 rounded-btn bg-primary px-5 h-10 text-aux font-medium text-white hover:bg-primary-deep">
            新建调研
          </button>
        </div>
      ) : (
        <motion.div variants={stagger} initial="initial" animate="animate" className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tasks.map((t) => {
            const proj = t.projection || {}
            const title = proj.report_title || t.query || t.task_id
            const ratio = proj.coverage?.ratio ?? (proj.coverage && proj.coverage.total ? proj.coverage.filled / proj.coverage.total : 0)
            const isTerminal = ['completed', 'failed', 'aborted'].includes(t.status)
            const canResume = t.status === 'failed' || t.status === 'aborted'
            return (
              <motion.div
                key={t.task_id}
                variants={fadeUp}
                className={`group flex flex-col rounded-card border border-line/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float ${t.status === 'completed' || t.status === 'running' || t.status === 'awaiting_clarify' ? 'cursor-pointer' : ''}`}
                onClick={() => openTask(t)}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-btn bg-primary-tint text-primary">
                    <FileText size={18} />
                  </span>
                  <span className={`rounded-chip px-2 py-0.5 text-tag ${STATUS_BADGE[t.status] ?? 'bg-bg text-ink-3'}`}>
                    {STATUS_LABEL[t.status] ?? t.status}
                  </span>
                </div>
                <h3 className="mt-3 line-clamp-2 text-aux font-semibold text-ink">{title}</h3>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(proj.brands ?? []).slice(0, 4).map((b) => (
                    <span key={b} className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">{b}</span>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-line/60 pt-3 text-tag text-ink-3">
                  <span className="inline-flex items-center gap-1">
                    <Network size={12} /> {proj.evidence_count ?? 0} 证据
                  </span>
                  {t.status === 'completed' && (
                    <span className="text-primary-deep">{(ratio * 100).toFixed(0)}% 覆盖</span>
                  )}
                  <span className="inline-flex items-center gap-1">
                    <Clock size={12} /> {t.created_at.slice(0, 10)}
                  </span>
                </div>

                {/* 操作按钮 */}
                <div className="mt-3 flex items-center gap-2">
                  {canResume && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onResume(t) }}
                      disabled={resuming === t.task_id}
                      className="inline-flex items-center gap-1 rounded-btn bg-primary px-3 h-8 text-tag font-medium text-white hover:bg-primary-deep disabled:opacity-50"
                    >
                      {resuming === t.task_id ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} 恢复
                    </button>
                  )}
                  {isTerminal && !canResume && (
                    <span className="text-tag text-ink-3">已结束</span>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); onDelete(t) }}
                    disabled={deleting === t.task_id}
                    className="ml-auto inline-flex items-center gap-1 rounded-btn px-2.5 h-8 text-tag text-risk/70 hover:bg-risk/10 hover:text-risk disabled:opacity-50"
                  >
                    {deleting === t.task_id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} 删除
                  </button>
                </div>
              </motion.div>
            )
          })}
        </motion.div>
      )}
    </div>
  )
}
