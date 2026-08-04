/* pi4 TracePage —— 调用级时间线表格(Q-F2-3)。
 * 不照搬 VerdaAI(依赖 expertStore + prompt/response 全文)。lean 重写:
 * 按 stage 分组(plan / search[含 subagent+judge] / write),每行 token(in→out)/latency/entity/model。
 * 砍 prompt/response/purpose/agent_id/decision/evidence_ids 列(pi4 轻量 span 无全文)。
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, Cpu, Clock, Activity } from 'lucide-react'
import { fetchTrace } from '../lib/api'
import type { TraceSpan } from '../types'

const STAGE_ORDER = ['plan', 'search', 'write']

function groupByStage(spans: TraceSpan[]): { stage: string; spans: TraceSpan[] }[] {
  const map = new Map<string, TraceSpan[]>()
  for (const s of spans) {
    const stage = s.stage || (s.kind === 'plan' ? 'plan' : s.kind === 'write' ? 'write' : 'search')
    if (!map.has(stage)) map.set(stage, [])
    map.get(stage)!.push(s)
  }
  const orderedStages = [
    ...STAGE_ORDER.filter((stage) => map.has(stage)),
    ...[...map.keys()].filter((stage) => !STAGE_ORDER.includes(stage)),
  ]
  return orderedStages.map((stage) => ({ stage, spans: map.get(stage)! }))
}

export default function TracePage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [spans, setSpans] = useState<TraceSpan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setSpans([])
    setError('')
    setLoading(Boolean(reportId))
    if (!reportId) return () => { active = false }

    fetchTrace(reportId)
      .then((next) => {
        if (active) setSpans(next)
      })
      .catch(() => {
        if (active) {
          setSpans([])
          setError('trace 加载失败，请稍后重试')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [reportId])

  const totals = useMemo(() => {
    const prompt = spans.reduce((a, s) => a + (s.prompt_tokens ?? 0), 0)
    const completion = spans.reduce((a, s) => a + (s.completion_tokens ?? 0), 0)
    const latency = spans.reduce((a, s) => a + (s.latency_ms ?? 0), 0)
    return { prompt, completion, latency, count: spans.length }
  }, [spans])

  const groups = useMemo(() => groupByStage(spans), [spans])

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button onClick={() => navigate(`/report/${reportId}`)} className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint hover:text-primary-deep">
          <ChevronLeft size={20} />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-btn bg-primary-tint text-primary">
          <Activity size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-aux font-medium text-ink">决策回放</div>
          <div className="text-tag text-ink-3">{reportId}</div>
        </div>
      </header>

      {/* 汇总 */}
      <div className="grid grid-cols-2 gap-3 border-b border-line bg-card/50 px-5 py-3 sm:grid-cols-4">
        <Stat icon={Activity} label="调用数" value={String(totals.count)} />
        <Stat icon={Cpu} label="prompt tokens" value={String(totals.prompt)} />
        <Stat icon={Cpu} label="completion tokens" value={String(totals.completion)} />
        <Stat icon={Clock} label="总延迟" value={`${(totals.latency / 1000).toFixed(1)}s`} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {loading ? (
          <div className="text-aux text-ink-3">加载 trace…</div>
        ) : error ? (
          <div className="text-aux text-risk">{error}</div>
        ) : groups.length === 0 ? (
          <div className="text-aux text-ink-3">无 trace span</div>
        ) : (
          <div className="mx-auto max-w-content flex flex-col gap-6">
            {groups.map((g) => (
              <div key={g.stage}>
                <div className="mb-2 flex items-center gap-2">
                  <h3 className="text-h3 capitalize text-ink">{g.stage}</h3>
                  <span className="text-tag text-ink-3">· {g.spans.length} 调用</span>
                </div>
                <div className="overflow-hidden rounded-card border border-line/60 bg-card shadow-card">
                  <table className="w-full text-tag">
                    <thead className="bg-bg/60 text-ink-3">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">seq</th>
                        <th className="px-3 py-2 text-left font-medium">kind</th>
                        <th className="px-3 py-2 text-left font-medium">entity</th>
                        <th className="px-3 py-2 text-left font-medium">model</th>
                        <th className="px-3 py-2 text-right font-medium">tokens (in→out)</th>
                        <th className="px-3 py-2 text-right font-medium">latency</th>
                        <th className="px-3 py-2 text-left font-medium">ts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.spans.map((s) => (
                        <tr key={s.span_id} className="border-t border-line/60 text-ink-2">
                          <td className="px-3 py-2 text-ink-3">{s.seq}</td>
                          <td className="px-3 py-2">
                            <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">{s.kind}</span>
                          </td>
                          <td className="px-3 py-2">{s.entity || '—'}</td>
                          <td className="px-3 py-2 text-ink-3">{s.model || '—'}</td>
                          <td className="px-3 py-2 text-right">
                            {s.prompt_tokens} → {s.completion_tokens}
                          </td>
                          <td className="px-3 py-2 text-right">{(s.latency_ms / 1000).toFixed(2)}s</td>
                          <td className="px-3 py-2 text-ink-3">{s.ts.slice(11, 19)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ icon: Icon, label, value }: { icon: typeof Cpu; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <Icon size={16} className="text-primary" />
      <div>
        <div className="text-tag text-ink-3">{label}</div>
        <div className="text-aux font-medium text-ink">{value}</div>
      </div>
    </div>
  )
}
