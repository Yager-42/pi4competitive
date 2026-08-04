/* pi4 EvidencesPage —— 全局证据库(Q-F3-2)。
 * 不照搬 VerdaAI KnowledgePage(文档搜索+批注)。从零写:
 * 左侧过滤侧栏(brand/source_type/min_confidence,选项从 facets 动态)+
 * 顶部 facets 汇总 + 右侧 evidence 卡片网格。
 */
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Database, Filter, Loader2, ExternalLink } from 'lucide-react'
import { fetchEvidences } from '../lib/api'
import type { Evidence, EvidenceQueryResp } from '../types'
import { fadeUp, stagger } from '../lib/motion'

const EMPTY: EvidenceQueryResp = { items: [], facets: { total: 0, by_type: {}, by_brand: {} } }

function safeHttpUrl(raw?: string): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'http:' || url.protocol === 'https:' ? raw : null
  } catch {
    return null
  }
}

export default function EvidencesPage() {
  const [data, setData] = useState<EvidenceQueryResp>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [brand, setBrand] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [minConf, setMinConf] = useState(0)
  const [limit, setLimit] = useState('200')

  useEffect(() => {
    const requestedLimit = Number(limit)
    if (!Number.isFinite(requestedLimit) || requestedLimit < 1) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    fetchEvidences({
      brand: brand || undefined,
      source_type: sourceType || undefined,
      min_confidence: minConf,
      limit: requestedLimit,
    })
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [brand, sourceType, minConf, limit])

  const brandOpts = Object.keys(data.facets.by_brand)
  const typeOpts = Object.keys(data.facets.by_type)

  return (
    <div className="mx-auto max-w-content px-8 py-10">
      <h1 className="text-h1 text-ink">证据库</h1>
      <p className="mt-1 text-aux text-ink-2">跨任务结构化证据溯源(entity/attribute/confidence 可检索)</p>

      {/* facets 汇总 */}
      <div className="mt-6 flex flex-wrap gap-3">
        <Summary label="证据总数" value={data.facets.total} />
        <Summary label="品牌数" value={brandOpts.length} />
        <Summary label="来源类型" value={typeOpts.length} />
      </div>

      <div className="mt-6 flex gap-6">
        {/* 过滤侧栏 */}
        <aside className="w-[240px] shrink-0">
          <div className="rounded-card border border-line/60 bg-card p-4 shadow-card">
            <div className="mb-3 flex items-center gap-1.5 text-aux font-medium text-ink">
              <Filter size={15} className="text-primary" /> 过滤
            </div>

            <label className="text-tag text-ink-3">品牌(brand)</label>
            <select
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              className="mt-1 h-9 w-full rounded-btn border border-line bg-bg px-2 text-aux text-ink outline-none focus:border-primary"
            >
              <option value="">全部</option>
              {brandOpts.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>

            <label className="mt-4 block text-tag text-ink-3">来源类型(source_type)</label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              className="mt-1 h-9 w-full rounded-btn border border-line bg-bg px-2 text-aux text-ink outline-none focus:border-primary"
            >
              <option value="">全部</option>
              {typeOpts.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>

            <label className="mt-4 block text-tag text-ink-3">
              最低置信度:{minConf.toFixed(2)}
            </label>
            <input
              type="range" min={0} max={1} step={0.1} value={minConf}
              onChange={(e) => setMinConf(Number(e.target.value))}
              className="mt-1 w-full accent-primary"
            />

            <label className="mt-4 block text-tag text-ink-3">数量上限</label>
            <input
              type="number" min={1} max={1000} value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className="mt-1 h-9 w-full rounded-btn border border-line bg-bg px-2 text-aux text-ink outline-none focus:border-primary"
            />
          </div>
        </aside>

        {/* 证据卡片网格 */}
        <div className="min-w-0 flex-1">
          {loading ? (
            <div className="flex items-center gap-2 text-aux text-ink-3">
              <Loader2 size={16} className="animate-spin" /> 加载证据…
            </div>
          ) : data.items.length === 0 ? (
            <div className="flex flex-col items-center text-ink-3">
              <Database size={40} strokeWidth={1.2} />
              <p className="mt-3 text-aux">无符合条件的证据</p>
            </div>
          ) : (
            <motion.div variants={stagger} initial="initial" animate="animate" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.items.map((ev, i) => (
                <EvidenceCard key={(ev.evidence_id ?? '') + i} ev={ev} />
              ))}
            </motion.div>
          )}
        </div>
      </div>
    </div>
  )
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-card border border-line/60 bg-card px-4 py-3 shadow-card">
      <div className="text-h2 font-semibold text-ink">{value}</div>
      <div className="text-tag text-ink-3">{label}</div>
    </div>
  )
}

function EvidenceCard({ ev }: { ev: Evidence }) {
  const conf = ev.confidence ?? 0
  const confColor = conf >= 0.7 ? 'text-ok' : conf >= 0.4 ? 'text-warn' : 'text-risk'
  const safeSource = safeHttpUrl(ev.source_url)
  return (
    <motion.div
      variants={fadeUp}
      className="flex flex-col rounded-card border border-line/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float"
    >
      <div className="flex items-center justify-between text-tag">
        <span className="font-medium text-ink-2">{ev.entity || '—'}</span>
        <span className={`rounded-chip bg-bg px-2 py-0.5 ${confColor}`}>
          {(conf * 100).toFixed(0)}%
        </span>
      </div>
      <div className="mt-1 text-tag text-ink-3">{ev.attribute || '—'}</div>
      <div className="mt-2 line-clamp-3 text-aux text-ink">{ev.value || ev.finding || '—'}</div>
      {safeSource && (
        <a
          href={safeSource}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 truncate text-tag text-primary hover:underline"
        >
          <ExternalLink size={11} /> {ev.source_url}
        </a>
      )}
    </motion.div>
  )
}
