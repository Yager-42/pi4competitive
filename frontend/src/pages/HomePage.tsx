/* pi4 HomePage —— 建任务入口。
 * 砍 VerdaAI 专家墙 / ModelPicker / 调研模式三档(pi4 无 mode,createTask 只收 query)。
 * 保留 Hero + 大输入框 + 示例卡 + submit → createTask(query) → clarify 或 workspace。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUp, Sparkles, Car, ShieldCheck, Layers, TrendingUp, Sprout } from 'lucide-react'
import { VSunGlow } from '../components/ui'
import { fadeUp, stagger } from '../lib/motion'
import { createTask } from '../lib/api'

const EXAMPLES = [
  {
    icon: Car,
    title: '新能源车竞争格局',
    desc: '分析特斯拉、比亚迪、理想的产品与定价竞争定位',
    q: '分析特斯拉、比亚迪、理想在新能源车市场的产品力与定价竞争格局',
  },
  {
    icon: ShieldCheck,
    title: '竞品 SWOT 分析',
    desc: '为飞书、钉钉、企业微信生成结构化 SWOT 对比',
    q: '为飞书、钉钉、企业微信做一份结构化 SWOT 竞争分析',
  },
  {
    icon: Layers,
    title: '功能对标基准',
    desc: '横向对比 Notion / 飞书 / Obsidian 的核心功能',
    q: '横向对比 Notion、飞书文档、Obsidian 的核心功能与定价',
  },
  {
    icon: TrendingUp,
    title: 'AI IDE 竞品对比',
    desc: 'Trae 与主流 AI 编程工具的对比',
    q: 'Trae 这款 AI IDE 的竞品对比',
  },
]

export default function HomePage() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  async function submit(q: string) {
    const query = q.trim()
    if (!query || submitting) return
    setSubmitting(true)
    setSubmitError('')
    try {
      const resp = await createTask(query)
      if (resp.status === 'awaiting_clarify' && resp.questions?.length) {
        navigate(`/clarify/${resp.task_id}`, { state: { query, clarify: resp.questions } })
      } else {
        navigate(`/workspace/${resp.task_id}`, { state: { query } })
      }
    } catch {
      setSubmitError('创建调研失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative min-h-full overflow-hidden">
      <div
        className="pointer-events-none absolute inset-0 -z-0 opacity-40"
        style={{
          background:
            'linear-gradient(180deg, rgba(234,241,234,0.6) 0%, rgba(250,251,249,0) 60%)',
        }}
      />
      <VSunGlow className="opacity-30" />

      <div className="relative z-10 flex items-center justify-between px-8 pt-6">
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card/80 px-3 h-9 text-aux text-ink-2 backdrop-blur">
          <Sparkles size={14} className="text-primary" /> 三阶段研究 · SearchOS coverage 引擎
        </span>
      </div>

      <div className="relative z-10 mx-auto flex min-h-[calc(100vh-80px)] max-w-[820px] flex-col items-center justify-center px-6 pb-20">
        <motion.h1
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="text-center font-serif text-[44px] leading-tight text-ink"
        >
          竞品分析,有据可依
          <span className="ml-2 inline-block align-middle">
            <Sprout className="inline text-primary" size={34} />
          </span>
        </motion.h1>
        <motion.p variants={fadeUp} initial="initial" animate="animate" className="mt-3 text-lg text-ink-2">
          你的 AI 竞品分析 Agent —— 三阶段搜索,无证据不立论
        </motion.p>

        <motion.div
          variants={fadeUp}
          initial="initial"
          animate="animate"
          className="mt-9 w-full rounded-card border-2 border-transparent bg-card p-4 shadow-float transition-all focus-within:border-primary focus-within:shadow-glow"
        >
          <textarea
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(text)
            }}
            placeholder="想分析哪个市场、公司或竞争策略?例如:Trae 的竞品对比 / Notion 与飞书的定价竞争"
            className="w-full resize-none bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-tag text-ink-3">真实联网搜索 · judge 抽证据 · coverage 驱动</span>
            <button
              onClick={() => submit(text)}
              disabled={!text.trim() || submitting}
              className="grid h-11 w-11 place-items-center rounded-full bg-primary text-white shadow-card transition-all hover:scale-105 hover:bg-primary-deep active:scale-95 disabled:opacity-40 disabled:hover:scale-100"
            >
              <ArrowUp size={20} />
            </button>
          </div>
        </motion.div>
        {submitError && <p className="mt-3 text-aux text-risk">{submitError}</p>}

        <p className="mt-9 text-aux text-ink-3">试试这些示例</p>
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="mt-4 grid w-full grid-cols-2 gap-4 sm:grid-cols-4"
        >
          {EXAMPLES.map((ex) => (
            <motion.button
              key={ex.title}
              variants={fadeUp}
              onClick={() => submit(ex.q)}
              className="group flex flex-col rounded-card border border-line/60 bg-card/80 p-4 text-left shadow-card backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-float"
            >
              <span className="grid h-9 w-9 place-items-center rounded-btn bg-primary-tint text-primary">
                <ex.icon size={18} />
              </span>
              <span className="mt-3 text-aux font-semibold text-ink">{ex.title}</span>
              <span className="mt-1 text-tag leading-relaxed text-ink-3">{ex.desc}</span>
            </motion.button>
          ))}
        </motion.div>
      </div>
    </div>
  )
}
