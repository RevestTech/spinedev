import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import SessionGate from './SessionGate'
import Layout from './components/Layout'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import PlanWizard from './pages/PlanWizard'
import Audits from './pages/Audits'
import AuditDetail from './pages/AuditDetail'
import Findings from './pages/Findings'
import Costs from './pages/Costs'
import SystemHealth from './pages/SystemHealth'
import WorkflowRuns from './pages/WorkflowRuns'
import LiveActivity from './pages/LiveActivity'
import Settings from './pages/Settings'
import Wiki from './pages/Wiki'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<SessionGate />}>
          <Route path="/login" element={<Login />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/projects/:id/plan" element={<PlanWizard />} />
            <Route path="/audits" element={<Audits />} />
            <Route path="/workflows" element={<WorkflowRuns />} />
            <Route path="/live" element={<LiveActivity />} />
            <Route path="/audits/:id" element={<AuditDetail />} />
            <Route path="/audits/:id/findings" element={<Findings />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="/health" element={<SystemHealth />} />
            <Route path="/wiki" element={<Wiki />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
