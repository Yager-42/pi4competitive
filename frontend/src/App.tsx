/* pi4 前端 router —— F1 工作台 + F2 报告闭环。
 * F3 加 /evidences / /dashboard / /knowledge。
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import HomePage from './pages/HomePage'
import ClarifyPage from './pages/ClarifyPage'
import WorkspacePage from './pages/WorkspacePage'
import ReportPage from './pages/ReportPage'
import LibraryPage from './pages/LibraryPage'
import TracePage from './pages/TracePage'
import GraphPage from './pages/GraphPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 带侧边栏框架的页面 */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/library" element={<LibraryPage />} />
        </Route>

        {/* 全屏沉浸页:澄清 / 工作台 / 报告 / trace / graph */}
        <Route path="/clarify/:taskId" element={<ClarifyPage />} />
        <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        <Route path="/report/:reportId" element={<ReportPage />} />
        <Route path="/trace/:reportId" element={<TracePage />} />
        <Route path="/graph/:reportId" element={<GraphPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
