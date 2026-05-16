import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { ProjectList } from './pages/ProjectList'
import { ProjectDetail } from './pages/ProjectDetail'
import { CostDashboard } from './pages/CostDashboard'
import { Layout } from './components/Layout'

function Dashboard() {
  return (
    <Layout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Welcome to Tron</h1>
          <p className="text-gray-600 mt-2">
            Enterprise AI QA Platform - Verify everything, trust nothing
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Projects</h3>
            <p className="text-gray-600 mb-4">
              View all your projects and their quality metrics
            </p>
            <a
              href="/projects"
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              View Projects →
            </a>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Costs</h3>
            <p className="text-gray-600 mb-4">
              Monitor your LLM costs and budget status
            </p>
            <a
              href="/costs"
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              View Costs →
            </a>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="font-semibold text-blue-900 mb-2">Getting Started</h3>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>
              • Create a new project to start running audits on your codebase
            </li>
            <li>• Monitor findings and track your code quality over time</li>
            <li>• Set up budget alerts to control your LLM spending</li>
            <li>• Use Temporal UI to view detailed workflow executions</li>
          </ul>
        </div>
      </div>
    </Layout>
  )
}

export function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects" element={<ProjectList />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
        <Route path="/costs" element={<CostDashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  )
}
