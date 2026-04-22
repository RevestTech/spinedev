import { useEffect } from 'react'
import { Layout } from '../components/Layout'
import { StatCard } from '../components/StatCard'
import {
  DollarSign,
  TrendingUp,
  AlertTriangle,
} from 'lucide-react'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

const costTrendData = [
  { date: 'Mon', cost: 8.5 },
  { date: 'Tue', cost: 9.2 },
  { date: 'Wed', cost: 7.8 },
  { date: 'Thu', cost: 10.5 },
  { date: 'Fri', cost: 11.3 },
  { date: 'Sat', cost: 6.2 },
  { date: 'Sun', cost: 14.7 },
]

const costByOperationData = [
  { name: 'BUILD', value: 42, color: '#3b82f6' },
  { name: 'FIX', value: 15, color: '#10b981' },
  { name: 'PLAN', value: 8, color: '#f59e0b' },
  { name: 'AUDIT', value: 3, color: '#ef4444' },
]

const costByProjectData = [
  { project: 'Mobile App', cost: 45 },
  { project: 'Website', cost: 12 },
  { project: 'API Service', cost: 8 },
  { project: 'Dashboard', cost: 3 },
]

const budgetAlerts = [
  {
    project: 'Mobile App',
    usage: 90,
    limit: 50,
    status: 'warning',
  },
  {
    project: 'Website',
    usage: 12,
    limit: 30,
    status: 'ok',
  },
  {
    project: 'API Service',
    usage: 26,
    limit: 50,
    status: 'ok',
  },
]

export function CostDashboard() {
  useEffect(() => {
    // Fetch cost data
  }, [])

  const todayCost = 14.7
  const monthCost = 68.2
  const monthBudget = 100
  const projectedMonthlyCost = 205
  const budgetUsagePercent = Math.round((monthCost / monthBudget) * 100)

  return (
    <Layout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Cost Management</h1>
          <p className="text-gray-600 mt-1">Track your LLM usage and costs</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            label="Today"
            value={`$${todayCost.toFixed(2)}`}
            icon={DollarSign}
            trend={{ value: 12, direction: 'up' }}
          />
          <StatCard
            label="This Month"
            value={`$${monthCost.toFixed(2)}`}
            trend={{ value: 8, direction: 'up' }}
          />
          <StatCard
            label="Budget"
            value={`$${monthBudget}`}
            trend={{ value: budgetUsagePercent, direction: 'up' }}
          />
          <StatCard
            label="Projected Monthly"
            value={`$${projectedMonthlyCost.toFixed(0)}`}
            icon={TrendingUp}
          />
        </div>

        {/* Budget Status */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-bold text-gray-900 mb-4">
            Budget Status
          </h2>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">
                  Monthly Budget Used
                </span>
                <span className="text-sm font-bold text-gray-900">
                  {budgetUsagePercent}% (${monthCost.toFixed(2)} / $
                  {monthBudget})
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className={`h-3 rounded-full transition-all ${
                    budgetUsagePercent > 90
                      ? 'bg-red-500'
                      : budgetUsagePercent > 70
                        ? 'bg-yellow-500'
                        : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.min(budgetUsagePercent, 100)}%` }}
                ></div>
              </div>
              <p className="text-xs text-gray-600 mt-2">
                {budgetUsagePercent <= 70
                  ? 'Budget usage is healthy'
                  : budgetUsagePercent <= 90
                    ? 'Approaching budget limit'
                    : 'Budget exceeded'}
              </p>
            </div>
          </div>
        </div>

        {/* Cost Trends and Breakdown */}
        <div className="grid grid-cols-2 gap-6">
          {/* Cost Trend Chart */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">
              Daily Cost Trend (Last 7 Days)
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={costTrendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="cost"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ fill: '#3b82f6' }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Cost by Operation */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">
              Cost by Operation
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={costByOperationData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) =>
                    `${name}: $${value} (${Math.round((value / 68) * 100)}%)`
                  }
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {costByOperationData.map((entry) => (
                    <Cell key={`cell-${entry.name}`} fill={entry.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cost by Project and Budget Alerts */}
        <div className="grid grid-cols-2 gap-6">
          {/* Cost by Project */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4">
              Cost by Project
            </h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={costByProjectData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="project" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="cost" fill="#3b82f6" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Budget Alerts */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-yellow-600" />
              Budget Alerts
            </h2>
            <div className="space-y-3">
              {budgetAlerts.map((alert) => (
                <div
                  key={alert.project}
                  className={`p-4 rounded-lg border ${
                    alert.status === 'warning'
                      ? 'bg-yellow-50 border-yellow-200'
                      : 'bg-gray-50 border-gray-200'
                  }`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <p className="font-medium text-gray-900">
                      {alert.project}
                    </p>
                    {alert.status === 'warning' && (
                      <span className="text-xs font-semibold text-yellow-800 bg-yellow-100 px-2 py-1 rounded">
                        Warning
                      </span>
                    )}
                  </div>
                  <div className="flex justify-between text-sm text-gray-600 mb-2">
                    <span>
                      ${alert.usage} / ${alert.limit}
                    </span>
                    <span>{Math.round((alert.usage / alert.limit) * 100)}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${
                        alert.status === 'warning' ? 'bg-yellow-500' : 'bg-green-500'
                      }`}
                      style={{
                        width: `${Math.min((alert.usage / alert.limit) * 100, 100)}%`,
                      }}
                    ></div>
                  </div>
                  {alert.status === 'warning' && (
                    <div className="mt-3 flex gap-2">
                      <button className="flex-1 px-3 py-2 text-xs font-medium text-yellow-700 bg-yellow-100 rounded hover:bg-yellow-200 transition-colors">
                        Increase Limit
                      </button>
                      <button className="flex-1 px-3 py-2 text-xs font-medium text-gray-700 bg-gray-100 rounded hover:bg-gray-200 transition-colors">
                        Throttle Usage
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Cost Breakdown by Model */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-bold text-gray-900 mb-4">
            Cost by LLM Model
          </h2>
          <div className="space-y-3">
            {[
              { model: 'Claude Sonnet', cost: 38, percent: 56 },
              { model: 'GPT-4o', cost: 20, percent: 29 },
              { model: 'Claude Haiku', cost: 10, percent: 15 },
            ].map((item) => (
              <div key={item.model}>
                <div className="flex justify-between mb-1">
                  <p className="text-sm font-medium text-gray-700">
                    {item.model}
                  </p>
                  <p className="text-sm font-bold text-gray-900">
                    ${item.cost} ({item.percent}%)
                  </p>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-accent h-2 rounded-full"
                    style={{ width: `${item.percent}%` }}
                  ></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Layout>
  )
}
