/* pi4 LibraryPage —— 我的调研(报告列表)。移植 VerdaAI 105 行版 + pi4 字段。
 * GET /api/v2/reports → {reports: ReportCard[]} → 卡片网格。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, Clock, Network } from 'lucide-react'
import { fetchReports } from '../lib/api'
import type { ReportCard } from '../types'
import { fadeUp, stagger } from '../lib/motion'

export default function LibraryPage() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportCard[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchReports()
      .then(setReports)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="mx-auto max-w-content px-8 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-h1 text-ink">我的调研</h1>
          <p className="mt-1 text-aux text-ink-2">已完成的研究报告,点击查看全文</p>
        </div>
      </div>

      {loading ? (
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="v-skeleton h-44 rounded-card" />
          ))}
        </div>
      ) : reports.length === 0 ? (
        <div className="mt-12 flex flex-col items-center text-ink-3">
          <FileText size={48} strokeWidth={1.2} />
          <p className="mt-4 text-aux">还没有调研报告</p>
          <button
            onClick={() => navigate('/')}
            className="mt-4 rounded-btn bg-primary px-5 h-10 text-aux font-medium text-white hover:bg-primary-deep"
          >
            新建调研
          </button>
        </div>
      ) : (
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {reports.map((r) => (
            <motion.button
              key={r.report_id}
              variants={fadeUp}
              onClick={() => navigate(`/report/${r.report_id}`)}
              className="group flex flex-col rounded-card border border-line/60 bg-card p-5 text-left shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-btn bg-primary-tint text-primary">
                  <FileText size={18} />
                </span>
                <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">
                  {(r.coverage_ratio * 100).toFixed(0)}% 覆盖
                </span>
              </div>
              <h3 className="mt-3 line-clamp-2 text-aux font-semibold text-ink">{r.title}</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {r.brands.slice(0, 4).map((b) => (
                  <span key={b} className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">
                    {b}
                  </span>
                ))}
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-line/60 pt-3 text-tag text-ink-3">
                <span className="inline-flex items-center gap-1">
                  <Network size={12} /> {r.evidence_count} 证据
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock size={12} /> {r.created_at.slice(0, 10)}
                </span>
              </div>
            </motion.button>
          ))}
        </motion.div>
      )}
    </div>
  )
}
