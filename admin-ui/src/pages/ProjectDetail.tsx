import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useProjectStore } from '../stores/projectStore'
import { useAuditStore } from '../stores/auditStore'
import { Layout } from '../components/Layout'
import { AuditProgress } from '../components/AuditProgress'
import { FindingCard } from '../components/FindingCard'
import { SeverityBadge } from '../components/SeverityBadge'
import {
  ArrowLeft,
  Play,
  TrendingUp,
  CheckCircle,
} from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

export function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { selectedProject, fetchProject, loading: projectLoading } =
    useProjectStore()
  const {
    selectedAudit,
    findings,
    fetchAudit,
    fetchAuditFindings,
    startAudit,
    pollAuditStatus,
  } = useAuditStore()

  const [isStartingAudit, setIsStartingAudit] = useState(false)
  const [showAuditDetail, setShowAuditDetail] = useState(false)

  useEffect(() => {
    if (projectId) {
      fetchProject(projectId)
    }
  }, [projectId, fetchProject])

  // Mock recent audits (in real app, would fetch from API)
  const recentAudits = [
    {
      id: '1',
      status: 'completed',
      createdAt: '2 hours ago',
      findings: 5,
    },
    { id: '2', status: 'completed', createdAt: '1 day ago', findings: 8 },
    { id: '3', status: 'completed', createdAt: '3 days ago', findings: 12 },
  ]

  const handleStartAudit = async () => {
    if (!projectId) return
    setIsStartingAudit(true)
    try {
      const audit = await startAudit(projectId)
      await fetchAudit(audit.id)
      setShowAuditDetail(true)

      // Set up polling
      const stopPolling = pollAuditStatus(audit.id, 2000)

      // Stop polling after 5 minutes or when complete
      setTimeout(stopPolling, 5 * 60 * 1000)
    } catch (error) {
      console.error('Failed to start audit:', error)
    } finally {
      setIsStartingAudit(false)
    }
  }

  const handleViewAuditDetails = async (auditId: string) => {
    await fetchAudit(auditId)
    await fetchAuditFindings(auditId)
    setShowAuditDetail(true)
  }

  if (projectLoading) {
    return (
      <Layout>
        <div className="text-center py-12">
          <p className="text-gray-600">Loading project...</p>
        </div>
      </Layout>
    )
  }

  if (!selectedProject) {
    return (
      <Layout>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-700">Project not found</p>
          <button
            onClick={() => navigate('/projects')}
            className="mt-4 text-red-600 hover:text-red-700 font-medium"
          >
            Back to Projects
          </button>
        </div>
      </Layout>
    )
  }

  const findingsBySeverity = [
    { severity: 'critical', count: 2 },
    { severity: 'high', count: 3 },
    { severity: 'medium', count: 4 },
    { severity: 'low', count: 1 },
  ]

  const scoreHistory = [
    { date: '7d ago', score: 82 },
    { date: '6d ago', score: 84 },
    { date: '5d ago', score: 86 },
    { date: '4d ago', score: 88 },
    { date: '3d ago', score: 90 },
    { date: '2d ago', score: 92 },
    { date: 'today', score: selectedProject.quality_score || 85 },
  ]

  return (
    <Layout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/projects')}
              className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-gray-600" />
            </button>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                {selectedProject.name}
              </h1>
              {selectedProject.description && (
                <p className="text-gray-600 mt-1">
                  {selectedProject.description}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleStartAudit}
            disabled={isStartingAudit}
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <Play className="w-4 h-4" />
            {isStartingAudit ? 'Starting...' : 'Run Audit'}
          </button>
        </div>

        {/* Active Audit Detail */}
        {showAuditDetail && selectedAudit && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex justify-between items-start mb-6">
              <h2 className="text-xl font-bold text-gray-900">
                Audit {selectedAudit.id.slice(0, 8)}...
              </h2>
              <button
                onClick={() => setShowAuditDetail(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <AuditProgress audit={selectedAudit} />

            {/* Findings for this audit */}
            {findings.length > 0 && (
              <div className="mt-6 pt-6 border-t border-gray-200">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">
                  Findings ({findings.length})
                </h3>
                <div className="space-y-3">
                  {findings.slice(0, 5).map((finding) => (
                    <FindingCard key={finding.id} finding={finding} />
                  ))}
                  {findings.length > 5 && (
                    <p className="text-center text-gray-600 pt-2">
                      +{findings.length - 5} more findings
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Quality Score Trend */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl font-bold text-gray-900">Quality Score</h2>
              <p className="text-gray-600 mt-1">Score trend over time</p>
            </div>
            <div className="text-right">
              <p className="text-4xl font-bold text-gray-900">
                {selectedProject.quality_score || 0}
              </p>
              <p className="text-sm text-green-600 flex items-center justify-end gap-1 mt-2">
                <TrendingUp className="w-4 h-4" />
                +2 this week
              </p>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={scoreHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="score"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ fill: '#3b82f6' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-2 gap-6">
          {/* Recent Audits */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-bold text-gray-900 mb-4">
              Recent Audits
            </h3>
            <div className="space-y-3">
              {recentAudits.map((audit) => (
                <button
                  key={audit.id}
                  onClick={() => handleViewAuditDetails(audit.id)}
                  className="w-full text-left p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="font-medium text-gray-900">Run #{audit.id}</p>
                      <p className="text-sm text-gray-600">{audit.createdAt}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm font-medium text-gray-700">
                        {audit.findings} findings
                      </span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Open Findings by Severity */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-bold text-gray-900 mb-4">
              Open Findings ({selectedProject.open_findings || 0})
            </h3>
            <div className="space-y-3">
              {findingsBySeverity.map((item) => (
                <div
                  key={item.severity}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                >
                  <SeverityBadge severity={item.severity} />
                  <span className="font-bold text-gray-900">{item.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Standards Compliance & Quick Actions */}
        <div className="grid grid-cols-2 gap-6">
          {/* Standards */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-bold text-gray-900 mb-4">
              Standards Compliance
            </h3>
            <div className="space-y-3">
              {[
                { name: 'Security', compliance: 95 },
                { name: 'Quality', compliance: 92 },
                { name: 'Performance', compliance: 78 },
              ].map((std) => (
                <div key={std.name}>
                  <div className="flex justify-between mb-1">
                    <p className="text-sm font-medium text-gray-700">
                      {std.name}
                    </p>
                    <p className="text-sm font-bold text-gray-900">
                      {std.compliance}%
                    </p>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-accent h-2 rounded-full"
                      style={{ width: `${std.compliance}%` }}
                    ></div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-bold text-gray-900 mb-4">
              Quick Actions
            </h3>
            <div className="space-y-2">
              <button className="w-full px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium">
                View All Findings
              </button>
              <button className="w-full px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium">
                Configure Standards
              </button>
              <a
                href="http://localhost:13008"
                target="_blank"
                rel="noopener noreferrer"
                className="block w-full px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium text-center"
              >
                View in Temporal UI
              </a>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
