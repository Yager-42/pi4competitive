/* pi4 GraphPage —— coverage_map 矩阵表格(Q-F2-4)。
 * 不照搬 VerdaAI d3 版。读 GET /reports/{id} 的 coverage_map 矩阵:
 * 行=entities,列=attributes,cell 四态着色(filled=绿/unknown=灰/conflict=红/empty=浅)。
 * 点 cell 弹 value/confidence/source;conflict 展示 candidates。
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, Network, Loader2, X } from 'lucide-react'
import { fetchReport } from '../lib/api'
import type { CoverageMatrix, CoverageMatrixCell } from '../types'

const STATUS_STYLE: Record<string, string> = {
  filled: 'bg-ok/20 text-ok border-ok/40',
  unknown: 'bg-ink-3/15 text-ink-3 border-line',
  conflict: 'bg-risk/20 text-risk border-risk/40',
  empty: 'bg-bg text-ink-3 border-line/60',
}
const STATUS_LABEL: Record<string, string> = {
  filled: '已填',
  unknown: '未找到',
  conflict: '冲突',
  empty: '待查',
}

function safeHttpUrl(raw?: string): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'http:' || url.protocol === 'https:' ? raw : null
  } catch {
    return null
  }
}

export default function GraphPage() {
  const { reportId } = useParams<{ reportId: string }>()
  const navigate = useNavigate()
  const [matrix, setMatrix] = useState<CoverageMatrix | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<{ cell: CoverageMatrixCell; entityName: string; attrName: string } | null>(null)

  useEffect(() => {
    if (!reportId) return
    fetchReport(reportId)
      .then((r) => {
        setMatrix(r?.coverage_map ?? null)
        setTitle(r?.title ?? reportId)
      })
      .finally(() => setLoading(false))
  }, [reportId])

  const cellMap = new Map<string, CoverageMatrixCell>()
  for (const c of matrix?.cells ?? []) {
    cellMap.set(`${c.entity_id}|${c.attribute_id}`, c)
  }
  const selectedSource = selected?.cell.source
  const safeSelectedSource = safeHttpUrl(selectedSource)

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button onClick={() => navigate(`/report/${reportId}`)} className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint hover:text-primary-deep">
          <ChevronLeft size={20} />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-btn bg-primary-tint text-primary">
          <Network size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">覆盖图谱 · {title}</div>
          <div className="text-tag text-ink-3">{matrix ? `${matrix.entities.length} 实体 × ${matrix.attributes.length} 属性` : reportId}</div>
        </div>
        {/* 图例 */}
        <div className="hidden items-center gap-3 sm:flex">
          {Object.entries(STATUS_LABEL).map(([k, label]) => (
            <span key={k} className="inline-flex items-center gap-1 text-tag text-ink-2">
              <span className={`h-3 w-3 rounded border ${STATUS_STYLE[k]}`} /> {label}
            </span>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-5">
        {loading ? (
          <div className="flex h-full items-center justify-center text-ink-3">
            <Loader2 className="animate-spin" size={28} />
          </div>
        ) : !matrix ? (
          <div className="flex h-full items-center justify-center text-aux text-ink-3">无 coverage_map 数据</div>
        ) : (
          <div className="inline-block min-w-full overflow-hidden rounded-card border border-line/60 bg-card shadow-card">
            <table className="border-collapse">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left text-tag font-medium text-ink-3">
                    实体 \ 属性
                  </th>
                  {matrix.attributes.map((a) => (
                    <th key={a.id} className="px-3 py-2 text-center text-tag font-medium text-ink-2">
                      <div>{a.name}</div>
                      <div className="text-[10px] text-ink-3">{a.dimension}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.entities.map((e) => (
                  <tr key={e.id} className="border-t border-line/60">
                    <td className="sticky left-0 z-10 bg-card px-3 py-2 text-aux font-medium text-ink">
                      {e.name}
                      <div className="text-[10px] text-ink-3">{e.kind}</div>
                    </td>
                    {matrix.attributes.map((a) => {
                      const cell = cellMap.get(`${e.id}|${a.id}`)
                      const status = cell?.status ?? 'empty'
                      return (
                        <td key={a.id} className="p-1">
                          <button
                            onClick={() =>
                              cell &&
                              setSelected({ cell, entityName: e.name, attrName: a.name })
                            }
                            className={`h-14 min-w-[80px] rounded-btn border px-2 text-center text-tag transition-all hover:shadow-card ${STATUS_STYLE[status]}`}
                            title={cell ? `${STATUS_LABEL[status]}: ${cell.value || '—'}` : STATUS_LABEL[status]}
                          >
                            {status === 'filled' ? (
                              <span className="line-clamp-2">{cell?.value || '✓'}</span>
                            ) : (
                              <span className="opacity-70">{STATUS_LABEL[status]}</span>
                            )}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* cell 详情弹层 */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/20 backdrop-blur-sm" onClick={() => setSelected(null)}>
          <div className="w-[420px] rounded-card border border-line bg-card p-5 shadow-float" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <div>
                <div className="text-tag text-ink-3">{selected.entityName} · {selected.attrName}</div>
                <span className={`mt-1 inline-flex items-center rounded-chip border px-2 py-0.5 text-tag ${STATUS_STYLE[selected.cell.status]}`}>
                  {STATUS_LABEL[selected.cell.status]}
                </span>
              </div>
              <button onClick={() => setSelected(null)} className="text-ink-3 hover:text-ink">
                <X size={18} />
              </button>
            </div>
            <div className="mt-3 text-body text-ink">{selected.cell.value || '(无值)'}</div>
            {selected.cell.confidence != null && (
              <div className="mt-2 text-tag text-ink-2">置信度:{(selected.cell.confidence * 100).toFixed(0)}%</div>
            )}
            {safeSelectedSource && (
              <a href={safeSelectedSource} target="_blank" rel="noreferrer" className="mt-2 block truncate text-tag text-primary hover:underline">
                {selectedSource}
              </a>
            )}
            {selected.cell.source_excerpt && (
              <p className="mt-2 rounded-btn bg-bg p-2 text-tag text-ink-2">“{selected.cell.source_excerpt}”</p>
            )}
            {selected.cell.candidates && selected.cell.candidates.length > 0 && (
              <div className="mt-3">
                <div className="text-tag font-semibold text-ink-3">候选(conflict)</div>
                <div className="mt-1 flex flex-col gap-1">
                  {selected.cell.candidates.map((c, i) => (
                    <div key={i} className="rounded-btn bg-bg px-2 py-1 text-tag text-ink-2">
                      {c.value} <span className="text-ink-3">· {(c.confidence * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
