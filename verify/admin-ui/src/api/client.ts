import axios, { AxiosInstance, AxiosError } from 'axios'
import {
  Project,
  ProjectListResponse,
  AuditRun,
  AuditListResponse,
  FindingListResponse,
  HealthResponse,
  ReadyResponse,
  CostDashboardData,
} from './types'

class APIClient {
  private client: AxiosInstance

  constructor(baseURL: string = '/api') {
    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    })

    // Add error interceptor for logging
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        console.error('API Error:', {
          status: error.response?.status,
          data: error.response?.data,
          message: error.message,
        })
        return Promise.reject(error)
      }
    )
  }

  // Projects
  async getProjects(page = 1, pageSize = 20, status?: string): Promise<ProjectListResponse> {
    const response = await this.client.get<ProjectListResponse>('/projects', {
      params: { page, page_size: pageSize, status },
    })
    return response.data
  }

  async getProject(id: string): Promise<Project> {
    const response = await this.client.get<Project>(`/projects/${id}`)
    return response.data
  }

  async createProject(project: {
    name: string
    description?: string
    repo_url?: string
    default_branch?: string
  }): Promise<Project> {
    const response = await this.client.post<Project>('/projects', project)
    return response.data
  }

  async updateProject(id: string, updates: Partial<Project>): Promise<Project> {
    const response = await this.client.put<Project>(`/projects/${id}`, updates)
    return response.data
  }

  async deleteProject(id: string): Promise<void> {
    await this.client.delete(`/projects/${id}`)
  }

  // Audits
  async getAudits(
    page = 1,
    pageSize = 20,
    projectId?: string,
    status?: string
  ): Promise<AuditListResponse> {
    const response = await this.client.get<AuditListResponse>('/audits', {
      params: {
        page,
        page_size: pageSize,
        project_id: projectId,
        status,
      },
    })
    return response.data
  }

  async getAudit(id: string): Promise<AuditRun> {
    const response = await this.client.get<AuditRun>(`/audits/${id}`)
    return response.data
  }

  async startAudit(projectId: string, branch = 'main'): Promise<AuditRun> {
    const response = await this.client.post<AuditRun>('/audits', {
      project_id: projectId,
      branch,
      trigger_type: 'manual',
    })
    return response.data
  }

  // Findings
  async getAuditFindings(
    auditId: string,
    page = 1,
    pageSize = 50,
    severity?: string,
    status?: string
  ): Promise<FindingListResponse> {
    const response = await this.client.get<FindingListResponse>(
      `/audits/${auditId}/findings`,
      {
        params: {
          page,
          page_size: pageSize,
          severity,
          status,
        },
      }
    )
    return response.data
  }

  // Costs
  async getCostDashboard(
    startDate?: string,
    endDate?: string
  ): Promise<CostDashboardData> {
    const response = await this.client.get<CostDashboardData>('/costs/dashboard', {
      params: { start_date: startDate, end_date: endDate },
    })
    return response.data
  }

  // Health checks
  async health(): Promise<HealthResponse> {
    const response = await this.client.get<HealthResponse>('/health')
    return response.data
  }

  async ready(): Promise<ReadyResponse> {
    const response = await this.client.get<ReadyResponse>('/ready')
    return response.data
  }
}

export const apiClient = new APIClient()
