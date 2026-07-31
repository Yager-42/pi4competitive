/* pi4 前端 router —— F1:工作台(AppLayout 内)+ 澄清/工作台全屏。
 * F2 加 /report/:reportId / /library;F3 加 /evidences / /dashboard / /graph。
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import HomePage from './pages/HomePage'
import ClarifyPage from './pages/ClarifyPage'
import WorkspacePage from './pages/WorkspacePage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 带侧边栏框架的页面 */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
        </Route>

        {/* 全屏沉浸页:澄清 / 工作台(F2 加 /report/:reportId) */}
        <Route path="/clarify/:taskId" element={<ClarifyPage />} />
        <Route path="/workspace/:taskId" element={<WorkspacePage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
