import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectStore } from '../stores/projectStore'
import { Layout } from '../components/Layout'
import { StatCard } from '../components/StatCard'
import { Folder, AlertCircle, Calendar, DollarSign, Plus } from 'lucide-react'
import { format } from 'date-fns'
import clsx from 'clsx'

function getStatusColor(score?: number) {
  if (!score) return 'bg-gray-50 border-gray-200'
  if (score >= 90) return 'bg-green-50 border-green-200 hover:border-green-300'
  if (score >= 70) return 'bg-yellow-50 border-yellow-200 hover:border-yellow-300'
  return 'bg-red-50 border-red-200 hover:border-red-300'
}

function getStatusBadge(score?: number) {
  if (!score) return { color: 'bg-gray-100 text-gray-800', text: 'No data' }
  if (score >= 90)
    return { color: 'bg-green-100 text-green-800', text: '🟢 Healthy' }
  if (score >= 70)
    return { color: 'bg-yellow-100 text-yellow-800', text: '🟡 Warning' }
  return { color: 'bg-red-100 text-red-800', text: '🔴 Critical' }
}

export function ProjectList() {
  const { projects, loading, error, fetchProjects } = useProjectStore()
  const [isCreating, setIsCreating] = useState(false)
  const [newProject, setNewProject] = useState({ name: '', description: '' })

  useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newProject.name) return

    try {
      await useProjectStore.getState().createProject({
        name: newProject.name,
        description: newProject.description,
        default_branch: 'main',
      })
      setNewProject({ name: '', description: '' })
      setIsCreating(false)
      fetchProjects()
    } catch (error) {
      console.error('Failed to create project:', error)
    }
  }

  const totalFindings = projects.reduce(
    (sum, p) => sum + (p.open_findings || 0),
    0
  )
  const avgScore =
    projects.length > 0
      ? Math.round(
          projects.reduce((sum, p) => sum + (p.quality_score || 0), 0) /
            projects.length
        )
      : 0

  return (
    <Layout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Projects</h1>
            <p className="text-gray-600 mt-1">
              Manage all your projects and view their audit status
            </p>
          </div>
          <button
            onClick={() => setIsCreating(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Project
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            label="Total Projects"
            value={projects.length}
            icon={Folder}
          />
          <StatCard label="Average Score" value={`${avgScore}/100`} />
          <StatCard
            label="Total Findings"
            value={totalFindings}
            icon={AlertCircle}
          />
          <StatCard
            label="Total Monthly Cost"
            value={`$${(projects.reduce((sum, p) => sum + (p.monthly_cost_usd || 0), 0)).toFixed(2)}`}
            icon={DollarSign}
          />
        </div>

        {/* Create Project Modal */}
        {isCreating && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 w-full max-w-md">
              <h2 className="text-xl font-bold text-gray-900 mb-4">
                Create New Project
              </h2>
              <form onSubmit={handleCreateProject} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Project Name
                  </label>
                  <input
                    type="text"
                    value={newProject.name}
                    onChange={(e) =>
                      setNewProject({ ...newProject, name: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent"
                    placeholder="e.g., Website"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Description
                  </label>
                  <textarea
                    value={newProject.description}
                    onChange={(e) =>
                      setNewProject({ ...newProject, description: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent"
                    placeholder="Optional description"
                    rows={3}
                  />
                </div>
                <div className="flex gap-3 justify-end pt-4">
                  <button
                    type="button"
                    onClick={() => setIsCreating(false)}
                    className="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors"
                  >
                    Create
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Projects Grid */}
        {loading ? (
          <div className="text-center py-12">
            <p className="text-gray-600">Loading projects...</p>
          </div>
        ) : error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700">{error}</p>
          </div>
        ) : projects.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
            <Folder className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-600">No projects yet</p>
            <button
              onClick={() => setIsCreating(true)}
              className="mt-4 px-4 py-2 bg-accent text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Create your first project
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((project) => {
              const statusBadge = getStatusBadge(project.quality_score)
              return (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className={clsx(
                    'border rounded-lg p-6 transition-all hover:shadow-lg cursor-pointer',
                    getStatusColor(project.quality_score)
                  )}
                >
                  <div className="space-y-4">
                    <div className="flex justify-between items-start">
                      <h3 className="font-bold text-gray-900 text-lg">
                        {project.name}
                      </h3>
                      <span
                        className={clsx(
                          'text-xs font-semibold px-3 py-1 rounded-full',
                          statusBadge.color
                        )}
                      >
                        {statusBadge.text}
                      </span>
                    </div>

                    {project.description && (
                      <p className="text-sm text-gray-600 line-clamp-2">
                        {project.description}
                      </p>
                    )}

                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-600">Quality Score</span>
                        <span className="font-bold text-gray-900">
                          {project.quality_score || 'N/A'}/100
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">Open Findings</span>
                        <span className="font-bold text-gray-900">
                          {project.open_findings || 0}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">Monthly Cost</span>
                        <span className="font-bold text-gray-900">
                          ${(project.monthly_cost_usd || 0).toFixed(2)}
                        </span>
                      </div>
                    </div>

                    {project.last_audit && (
                      <div className="flex items-center gap-2 text-xs text-gray-500 pt-2 border-t border-current border-opacity-10">
                        <Calendar className="w-3 h-3" />
                        Last audit:{' '}
                        {format(
                          new Date(project.last_audit),
                          'MMM d, HH:mm'
                        )}
                      </div>
                    )}
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </Layout>
  )
}
