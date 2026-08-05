/* pi4 ReportPage —— 精简重写(Q6 降级)。
 * 不照搬 VerdaAI 676 行版(依赖 12 个 pi4 不支持的子组件)。
 * markdown 渲染 + coverage 侧栏 + sources + refine(section 级)+ feedback + trace/graph 入口。
 * 砍 claims/charts/sentiment/audit/quality/datagrid/structured/选区高亮。
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronLeft, Activity, Network, ShieldCheck, Sparkles, Loader2 } from 'lucide-react'
import { fetchReport, refineSection, submitFeedback } from '../lib/api'
import type { Report, ReportSection } from '../types'


function safeHttpUrl(raw?: string): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'http:' || url.protocol === 'https:' ? raw : null
  } catch {
    return null
  }
}
export default function ReportPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [refining, setRefining] = useState<string | null>(null) // section id being refined
  const [annoInput, setAnnoInput] = useState<Record<string, string>>({})
  const [fbEdited, setFbEdited] = useState(0)
  const [fbTotal, setFbTotal] = useState(0)
  const [fbMsg, setFbMsg] = useState('')
  const [refineErrors, setRefineErrors] = useState<Record<string, string>>({})

  async function load() {
    if (!reportId) return
    setLoading(true)
    try {
      const r = await fetchReport(reportId)
      setReport(r)
      setFbTotal(r?.sections?.length ?? 0)
    } catch {
      setReport(null)
      setFbTotal(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId])

  async function doRefine(s: ReportSection) {
    if (!reportId || refining) return
    setRefining(s.id)
    setRefineErrors((prev) => ({ ...prev, [s.id]: '' }))
    const annotations = (annoInput[s.id] ?? '')
      .split(/[,，\n]+/)
      .map((x) => x.trim())
      .filter(Boolean)
    try {
      const response = await refineSection(reportId, s.id, annotations)
      if (!response.ok) {
        setRefineErrors((prev) => ({
          ...prev,
          [s.id]: response.message ?? '章节深化失败，请稍后重试',
        }))
        return
      }
      await load() // re-fetch: refine stage_output 优先,section 标 refined
    } catch {
      setRefineErrors((prev) => ({ ...prev, [s.id]: '章节深化失败，请稍后重试' }))
    } finally {
      setRefining(null)
    }
  }

  async function doFeedback() {
    if (!reportId) return
    setFbMsg('')
    try {
      const r = await submitFeedback(reportId, fbEdited, fbTotal)
      setFbMsg(r.ok ? `已记录修正率 ${((r.revision_rate ?? 0) * 100).toFixed(0)}%` : '提交失败')
    } catch {
      setFbMsg('提交失败，请稍后重试')
    }
  }


  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center text-ink-3">
        <Loader2 className="animate-spin" size={28} />
      </div>
    )
  }

  if (!report || report.ok === false) {
    return (
      <div className="flex h-screen flex-col items-center justify-center text-ink-3">
        <p className="text-aux">{report?.message || '报告未就绪或不存在'}</p>
        <button onClick={() => navigate('/library')} className="mt-4 rounded-btn bg-primary px-5 h-10 text-aux text-white">
          返回列表
        </button>
      </div>
    )
  }

  const cov = report.coverage
  const ratio = cov?.ratio ?? (cov && cov.total ? cov.filled / cov.total : 0)
  const sources = (report.sources ?? []).slice(0, 20).map((src) => ({ src, href: safeHttpUrl(src) }))

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button onClick={() => navigate('/library')} className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint hover:text-primary-deep">
          <ChevronLeft size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">{report.title}</div>
          <div className="text-tag text-ink-3">{report.report_id}</div>
        </div>
        <button
          onClick={() => navigate(`/trace/${reportId}`)}
          className="inline-flex items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux text-primary-deep hover:bg-primary-soft/40"
        >
          <Activity size={15} /> 决策回放
        </button>
        <button
          onClick={() => navigate(`/graph/${reportId}`)}
          className="inline-flex items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux text-primary-deep hover:bg-primary-soft/40"
        >
          <Network size={15} /> 覆盖图谱
        </button>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* 主区:sections markdown */}
        <div className="min-w-0 flex-1 overflow-y-auto px-8 py-8">
          <div className="mx-auto max-w-read">
            <h1 className="text-h1 text-ink">{report.title}</h1>
            {report.sections && report.sections.length > 0 ? (
              <div className="mt-6 flex flex-col gap-6">
                {report.sections.map((s) => (
                  <motion.div
                    key={s.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="rounded-card border border-line/60 bg-card p-6 shadow-card"
                  >
                    <div className="mb-3 flex items-center justify-between">
                      <h2 className="text-h2 text-ink">{s.title}</h2>
                      {s.refined && (
                        <span className="inline-flex items-center gap-1 rounded-chip bg-ok/15 px-2 py-0.5 text-tag text-ok">
                          <Sparkles size={11} /> 已深化
                        </span>
                      )}
                    </div>
                    <div className="prose prose-sm max-w-none text-body text-ink-2">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.body}</ReactMarkdown>
                    </div>
                    {/* refine section 级 */}
                    <div className="mt-4 border-t border-line/60 pt-3">
                      <input
                        value={annoInput[s.id] ?? ''}
                        onChange={(e) => setAnnoInput((m) => ({ ...m, [s.id]: e.target.value }))}
                        placeholder="批注:补充更详细的定价数据与对比(逗号分隔多条)"
                        className="h-9 w-full rounded-btn border border-line bg-bg px-3 text-aux text-ink outline-none focus:border-primary"
                      />
                      <button
                        onClick={() => doRefine(s)}
                        disabled={refining === s.id}
                        className="mt-2 inline-flex items-center gap-1.5 rounded-btn bg-primary px-4 h-9 text-aux font-medium text-white hover:bg-primary-deep disabled:opacity-50"
                      >
                        {refining === s.id ? <><Loader2 size={14} className="animate-spin" /> 深化中…</> : '深化此章节'}
                      </button>
                      {refineErrors[s.id] && <p className="mt-2 text-tag text-risk">{refineErrors[s.id]}</p>}
                    </div>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="mt-6 prose prose-sm max-w-none text-body text-ink-2">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.markdown || '(无内容)'}</ReactMarkdown>
              </div>
            )}
          </div>
        </div>

        {/* 侧栏:coverage + sources + feedback */}
        <aside className="w-[300px] shrink-0 overflow-y-auto border-l border-line bg-card/50 p-5">
          <div className="text-tag font-semibold uppercase tracking-wider text-ink-3">覆盖率</div>
          <div className="mt-3 rounded-card border border-line/60 bg-card p-4 shadow-card">
            <div className="flex items-center justify-between text-aux text-ink-2">
              <span>{cov?.filled ?? 0} / {cov?.total ?? 0} cell</span>
              <span className="font-medium text-primary-deep">{(ratio * 100).toFixed(0)}%</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-chip bg-line">
              <div className="h-full rounded-chip bg-primary" style={{ width: `${ratio * 100}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-tag text-ink-3">
              <span>unknown {cov?.unknown ?? 0}</span>
              <span>conflict {cov?.conflict ?? 0}</span>
            </div>
          </div>

          <div className="mt-5 flex items-center justify-between">
            <span className="text-tag font-semibold uppercase tracking-wider text-ink-3">证据</span>
            <span className="text-tag text-ink-2">{report.evidence_count ?? 0} 条</span>
          </div>

          <div className="mt-3 text-tag font-semibold uppercase tracking-wider text-ink-3">来源</div>
          <div className="mt-2 flex flex-col gap-1">
            {sources.map(({ src, href }, i) => (
              href ? (
                <a
                  key={i}
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate rounded-btn px-2 py-1 text-tag text-ink-2 hover:bg-primary-tint hover:text-primary-deep"
                >
                  {src}
                </a>
              ) : (
                <span key={i} className="truncate rounded-btn px-2 py-1 text-tag text-ink-3">{src}</span>
              )
            ))}
            {sources.length === 0 && <span className="text-tag text-ink-3">(无)</span>}
          </div>

          {/* feedback 修正率 */}
          <div className="mt-6 rounded-card border border-line/60 bg-card p-4 shadow-card">
            <div className="flex items-center gap-1.5 text-aux font-medium text-ink">
              <ShieldCheck size={15} className="text-primary" /> 修正率
            </div>
            <div className="mt-2 flex items-center gap-2 text-tag text-ink-2">
              <input
                type="number" min={0} max={fbTotal} value={fbEdited}
                onChange={(e) => setFbEdited(Number(e.target.value))}
                className="h-8 w-16 rounded-btn border border-line bg-bg px-2 text-tag outline-none focus:border-primary"
              />
              <span>/ {fbTotal} 章节手动编辑</span>
            </div>
            <button
              onClick={doFeedback}
              className="mt-2 w-full rounded-btn bg-primary h-9 text-aux font-medium text-white hover:bg-primary-deep"
            >
              提交修正率
            </button>
            {fbMsg && <p className="mt-2 text-tag text-primary-deep">{fbMsg}</p>}
          </div>
        </aside>
      </div>
    </div>
  )
}
