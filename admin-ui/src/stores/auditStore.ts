import { create } from 'zustand'
import { apiClient } from '../api/client'
import { AuditRun, Finding } from '../api/types'

interface AuditState {
  audits: AuditRun[]
  selectedAudit: AuditRun | null
  findings: Finding[]
  loading: boolean
  error: string | null
  pagination: {
    page: number
    pageSize: number
    total: number
  }
  findingsPagination: {
    page: number
    pageSize: number
    total: number
  }

  // Actions
  fetchAudits: (
    page?: number,
    pageSize?: number,
    projectId?: string
  ) => Promise<void>
  fetchAudit: (id: string) => Promise<void>
  fetchAuditFindings: (
    auditId: string,
    page?: number,
    pageSize?: number
  ) => Promise<void>
  startAudit: (projectId: string) => Promise<AuditRun>
  setSelectedAudit: (audit: AuditRun | null) => void
  clearError: () => void
  pollAuditStatus: (auditId: string, intervalMs?: number) => () => void
}

export const useAuditStore = create<AuditState>((set, _get) => ({
  audits: [],
  selectedAudit: null,
  findings: [],
  loading: false,
  error: null,
  pagination: {
    page: 1,
    pageSize: 20,
    total: 0,
  },
  findingsPagination: {
    page: 1,
    pageSize: 50,
    total: 0,
  },

  fetchAudits: async (page = 1, pageSize = 20, projectId?: string) => {
    set({ loading: true, error: null })
    try {
      const data = await apiClient.getAudits(page, pageSize, projectId)
      set({
        audits: data.items,
        pagination: {
          page: data.page,
          pageSize: data.page_size,
          total: data.total,
        },
        loading: false,
      })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch audits',
        loading: false,
      })
    }
  },

  fetchAudit: async (id: string) => {
    set({ loading: true, error: null })
    try {
      const audit = await apiClient.getAudit(id)
      set({
        selectedAudit: audit,
        loading: false,
      })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch audit',
        loading: false,
      })
    }
  },

  fetchAuditFindings: async (auditId: string, page = 1, pageSize = 50) => {
    set({ loading: true, error: null })
    try {
      const data = await apiClient.getAuditFindings(auditId, page, pageSize)
      set({
        findings: data.items,
        findingsPagination: {
          page: data.page,
          pageSize: data.page_size,
          total: data.total,
        },
        loading: false,
      })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch findings',
        loading: false,
      })
    }
  },

  startAudit: async (projectId: string) => {
    set({ loading: true, error: null })
    try {
      const audit = await apiClient.startAudit(projectId)
      set((state) => ({
        audits: [audit, ...state.audits],
        loading: false,
      }))
      return audit
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start audit'
      set({ error: message, loading: false })
      throw error
    }
  },

  setSelectedAudit: (audit) => set({ selectedAudit: audit }),

  clearError: () => set({ error: null }),

  pollAuditStatus: (auditId: string, intervalMs = 3000) => {
    const interval = setInterval(async () => {
      try {
        const audit = await apiClient.getAudit(auditId)
        set((state) => ({
          selectedAudit: audit,
          audits: state.audits.map((a) => (a.id === auditId ? audit : a)),
        }))

        // Stop polling if audit is complete
        if (
          audit.status === 'completed' ||
          audit.status === 'failed' ||
          audit.status === 'cancelled'
        ) {
          clearInterval(interval)
        }
      } catch (error) {
        console.error('Error polling audit status:', error)
      }
    }, intervalMs)

    return () => clearInterval(interval)
  },
}))
