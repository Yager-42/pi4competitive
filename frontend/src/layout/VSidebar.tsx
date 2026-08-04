/* pi4 侧边栏 —— F1 只放「工作台」项;F2/F3 加报告/证据库/仪表盘等。
 * 工作空间用量卡读 pi4 GET /api/v2/dashboard(reports/evidence_total)。
 */
import { useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { Home, Sprout, ChevronDown, Radar, BarChart3, Library } from 'lucide-react'

const navItems = [
  { to: '/', label: '工作台', icon: Home, end: true },
  { to: '/library', label: '我的调研', icon: BarChart3 },
  { to: '/evidences', label: '证据库', icon: Library },
  { to: '/dashboard', label: '竞争情报中心', icon: Radar },
]

export default function VSidebar() {
  const navigate = useNavigate()
  const [reports, setReports] = useState(0)
  const [evidence, setEvidence] = useState(0)

  useEffect(() => {
    fetch('/api/v2/dashboard')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d) {
          setReports(d.reports ?? 0)
          setEvidence(d.evidence_total ?? 0)
        }
      })
      .catch(() => {
        /* 后端未启动时静默(不白屏) */
      })
  }, [])

  return (
    <aside className="relative flex h-full w-[220px] shrink-0 flex-col border-r border-line bg-card/70">
      <button onClick={() => navigate('/')} className="flex items-center gap-2.5 px-6 pt-6 pb-7">
        <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
          <Sprout size={22} strokeWidth={1.8} />
        </span>
        <span className="text-[20px] font-semibold tracking-tight text-ink">CompetitorLens</span>
      </button>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                'flex h-11 items-center gap-3 rounded-btn px-3.5 text-[15px] transition-all ease-verda',
                isActive
                  ? 'bg-primary-tint font-medium text-primary-deep'
                  : 'text-ink-2 hover:bg-primary-tint/50',
              ].join(' ')
            }
          >
            <item.icon size={19} strokeWidth={1.8} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="mx-3 mb-3 rounded-card border border-line/70 bg-primary-tint/40 p-4">
        <div className="flex items-center gap-2">
          <Sprout size={16} className="text-primary" strokeWidth={2} />
          <span className="text-aux font-semibold text-ink">我的工作空间</span>
        </div>
        <p className="mt-1 text-tag text-ink-3">累计完成 {reports} 次调研</p>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-chip bg-line">
          <div
            className="h-full rounded-chip bg-primary transition-all"
            style={{ width: `${Math.min(100, reports * 10)}%` }}
          />
        </div>
        <p className="mt-1.5 text-right text-tag text-ink-3">已沉淀 {evidence} 条证据</p>
      </div>

      <div className="flex items-center gap-3 border-t border-line px-4 py-3.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-sun text-[13px] font-semibold text-ink">
          研
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">研究员</div>
          <div className="truncate text-tag text-ink-3">CompetitorLens</div>
        </div>
        <ChevronDown size={16} className="text-ink-3" />
      </div>
    </aside>
  )
}
