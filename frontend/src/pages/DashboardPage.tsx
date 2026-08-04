/* pi4 DashboardPage —— 竞争情报中心,内嵌订阅管理(Q-F3-1)。
 * 不照搬 VerdaAI 584 行版(依赖 fetchWorkload 专家工作量 + 业务伪指标)。
 * 渲染 pi4 11 指标 + tasks_by_status 分布 + brand/source_type 分布 + 订阅 CRUD+run。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  FileText, Database, Cpu, Gauge, CheckCircle2, Plus, Trash2, Play, Loader2,
} from 'lucide-react'
import { fetchDashboard, fetchSubscriptions, createSubscription, deleteSubscription, runSubscription } from '../lib/api'
import type { DashboardStats, Subscription } from '../types'
import { VCountUp } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-ok',
  failed: 'bg-risk',
  aborted: 'bg-risk',
  running: 'bg-primary',
  pending: 'bg-warn',
  awaiting_clarify: 'bg-info',
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [subs, setSubs] = useState<Subscription[]>([])
  const [loading, setLoading] = useState(true)
  const [newQuery, setNewQuery] = useState('')
  const [newBrands, setNewBrands] = useState('')
  const [running, setRunning] = useState<string | null>(null)
  const [subError, setSubError] = useState('')

  async function load() {
    setLoading(true)
    const [d, s] = await Promise.all([fetchDashboard(), fetchSubscriptions()])
    setStats(d)
    setSubs(s)
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  async function addSub() {
    if (!newQuery.trim()) return
    const brands = newBrands.split(/[,，\s]+/).map((b) => b.trim()).filter(Boolean)
    const created = await createSubscription(newQuery.trim(), brands)
    if (!created) {
      setSubError('创建订阅失败，请稍后重试')
      return
    }
    setSubError('')
    setNewQuery('')
    setNewBrands('')
    await load()
  }

  async function delSub(id: string) {
    await deleteSubscription(id)
    await load()
  }

  async function runSub(id: string) {
    setRunning(id)
    const r = await runSubscription(id)
    if (r.ok && r.task_id) navigate(`/workspace/${r.task_id}`, { state: { query: '' } })
    setRunning(null)
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-ink-3">
        <Loader2 className="animate-spin" size={28} />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-ink-3">
        <p className="text-aux">仪表盘加载失败，请稍后重试</p>
        <button onClick={load} className="mt-4 rounded-btn bg-primary px-5 h-10 text-aux text-white hover:bg-primary-deep">
          重试
        </button>
      </div>
    )
  }

  const maxStatus = Math.max(1, ...Object.values(stats.tasks_by_status || {}))

  return (
    <div className="mx-auto max-w-content px-8 py-10">
      <h1 className="text-h1 text-ink">竞争情报中心</h1>
      <p className="mt-1 text-aux text-ink-2">全局调研统计与监控订阅</p>

      {/* 指标卡 */}
      <motion.div variants={stagger} initial="initial" animate="animate" className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard icon={FileText} label="报告" value={stats.reports} color="text-primary" />
        <MetricCard icon={Database} label="证据" value={stats.evidence_total} color="text-info" />
        <MetricCard icon={Cpu} label="累计 token" value={stats.token_total} color="text-warn" />
        <MetricCard icon={Gauge} label="平均覆盖率" value={`${(stats.avg_coverage * 100).toFixed(0)}%`} color="text-ok" />
        <MetricCard icon={CheckCircle2} label="事实准确率" value={`${stats.fact_accuracy}%`} color="text-ok" />
        <MetricCard icon={Database} label="高置信证据" value={stats.high_conf_total} color="text-ok" />
      </motion.div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* tasks_by_status 分布 */}
        <Panel title="任务状态分布">
          <div className="flex flex-col gap-2">
            {Object.entries(stats.tasks_by_status || {}).map(([st, n]) => (
              <div key={st} className="flex items-center gap-2">
                <span className="w-32 shrink-0 text-tag text-ink-2">{st}</span>
                <div className="h-3 flex-1 overflow-hidden rounded-chip bg-line">
                  <div
                    className={`h-full rounded-chip ${STATUS_COLORS[st] ?? 'bg-ink-3'}`}
                    style={{ width: `${(n / maxStatus) * 100}%` }}
                  />
                </div>
                <span className="w-6 text-right text-tag text-ink">{n}</span>
              </div>
            ))}
            {Object.keys(stats.tasks_by_status || {}).length === 0 && (
              <span className="text-aux text-ink-3">无任务</span>
            )}
          </div>
        </Panel>

        {/* brand 分布 */}
        <Panel title="品牌分布">
          <DistRows dist={stats.brand_distribution} />
        </Panel>
      </div>

      {/* source_type 分布 */}
      <div className="mt-4">
        <Panel title="来源类型分布">
          <DistRows dist={stats.source_type_distribution} />
        </Panel>
      </div>

      {/* 内嵌订阅管理 */}
      <div className="mt-8">
        <h2 className="text-h2 text-ink">监控订阅</h2>
        <p className="mt-1 text-aux text-ink-2">保存查询,手动触发重跑(无定时器,定期靠外部 cron)</p>

        {/* 新建 */}
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-card border border-line/60 bg-card p-4 shadow-card">
          <input
            value={newQuery}
            onChange={(e) => setNewQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addSub()}
            placeholder="订阅查询(如:Trae 竞品对比)"
            className="h-10 min-w-[240px] flex-1 rounded-btn border border-line bg-bg px-3 text-aux text-ink outline-none focus:border-primary"
          />
          <input
            value={newBrands}
            onChange={(e) => setNewBrands(e.target.value)}
            placeholder="预置竞品(逗号分隔,可选)"
            className="h-10 w-[240px] rounded-btn border border-line bg-bg px-3 text-aux text-ink outline-none focus:border-primary"
          />
          <button
            onClick={addSub}
            disabled={!newQuery.trim()}
            className="inline-flex items-center gap-1.5 rounded-btn bg-primary px-4 h-10 text-aux font-medium text-white hover:bg-primary-deep disabled:opacity-50"
          >
            <Plus size={16} /> 新建订阅
          </button>
          {subError && <p className="mt-2 text-tag text-risk">{subError}</p>}
        </div>

        {/* 订阅列表 */}
        <div className="mt-4 flex flex-col gap-2">
          {subs.length === 0 && <div className="text-aux text-ink-3">尚无订阅</div>}
          {subs.map((s) => (
            <div key={s.sub_id} className="flex items-center gap-3 rounded-card border border-line/60 bg-card p-3 shadow-card">
              <div className="min-w-0 flex-1">
                <div className="truncate text-aux font-medium text-ink">{s.query}</div>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {s.brands.map((b) => (
                    <span key={b} className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">{b}</span>
                  ))}
                </div>
              </div>
              <div className="text-right text-tag text-ink-3">
                <div>已跑 {s.run_count} 次</div>
                <div>{s.last_run_at ? s.last_run_at.slice(0, 10) : '未运行'}</div>
              </div>
              <button
                onClick={() => runSub(s.sub_id)}
                disabled={running === s.sub_id}
                className="inline-flex items-center gap-1 rounded-btn bg-primary-tint px-3 h-9 text-aux text-primary-deep hover:bg-primary-soft/40 disabled:opacity-50"
              >
                {running === s.sub_id ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} 重跑
              </button>
              <button
                onClick={() => delSub(s.sub_id)}
                className="grid h-9 w-9 place-items-center rounded-btn text-risk/70 hover:bg-risk/10 hover:text-risk"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function MetricCard({ icon: Icon, label, value, color }: { icon: typeof FileText; label: string; value: number | string; color: string }) {
  return (
    <motion.div variants={fadeUp} className="rounded-card border border-line/60 bg-card p-4 shadow-card">
      <Icon size={20} className={color} strokeWidth={1.8} />
      <div className="mt-2 text-h2 font-semibold text-ink">
        {typeof value === 'number' ? <VCountUp value={value} /> : value}
      </div>
      <div className="text-tag text-ink-3">{label}</div>
    </motion.div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-card border border-line/60 bg-card p-5 shadow-card">
      <div className="mb-3 text-tag font-semibold uppercase tracking-wider text-ink-3">{title}</div>
      {children}
    </div>
  )
}

function DistRows({ dist }: { dist: Record<string, number> }) {
  const entries = Object.entries(dist || {})
  const max = Math.max(1, ...entries.map(([, n]) => n))
  if (entries.length === 0) return <span className="text-aux text-ink-3">无数据</span>
  return (
    <div className="flex flex-col gap-2">
      {entries.map(([k, n]) => (
        <div key={k} className="flex items-center gap-2">
          <span className="w-28 shrink-0 truncate text-tag text-ink-2">{k || '(空)'}</span>
          <div className="h-3 flex-1 overflow-hidden rounded-chip bg-line">
            <div className="h-full rounded-chip bg-primary" style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className="w-8 text-right text-tag text-ink">{n}</span>
        </div>
      ))}
    </div>
  )
}
