import { create } from 'zustand'
import { apiClient } from '../api/client'
import { Project } from '../api/types'

interface ProjectState {
  projects: Project[]
  selectedProject: Project | null
  loading: boolean
  error: string | null
  pagination: {
    page: number
    pageSize: number
    total: number
  }

  // Actions
  fetchProjects: (page?: number, pageSize?: number) => Promise<void>
  fetchProject: (id: string) => Promise<void>
  createProject: (data: Partial<Project>) => Promise<Project>
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: (id: string) => Promise<void>
  setSelectedProject: (project: Project | null) => void
  clearError: () => void
}

export const useProjectStore = create<ProjectState>((set, _get) => ({
  projects: [],
  selectedProject: null,
  loading: false,
  error: null,
  pagination: {
    page: 1,
    pageSize: 20,
    total: 0,
  },

  fetchProjects: async (page = 1, pageSize = 20) => {
    set({ loading: true, error: null })
    try {
      const data = await apiClient.getProjects(page, pageSize)
      set({
        projects: data.items,
        pagination: {
          page: data.page,
          pageSize: data.page_size,
          total: data.total,
        },
        loading: false,
      })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch projects',
        loading: false,
      })
    }
  },

  fetchProject: async (id: string) => {
    set({ loading: true, error: null })
    try {
      const project = await apiClient.getProject(id)
      set({ selectedProject: project, loading: false })
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch project',
        loading: false,
      })
    }
  },

  createProject: async (data: Partial<Project>) => {
    set({ loading: true, error: null })
    try {
      const project = await apiClient.createProject(data as any)
      set((state) => ({
        projects: [project, ...state.projects],
        loading: false,
      }))
      return project
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create project'
      set({ error: message, loading: false })
      throw error
    }
  },

  updateProject: async (id: string, data: Partial<Project>) => {
    set({ loading: true, error: null })
    try {
      const updated = await apiClient.updateProject(id, data)
      set((state) => ({
        projects: state.projects.map((p) => (p.id === id ? updated : p)),
        selectedProject:
          state.selectedProject?.id === id ? updated : state.selectedProject,
        loading: false,
      }))
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update project',
        loading: false,
      })
    }
  },

  deleteProject: async (id: string) => {
    set({ loading: true, error: null })
    try {
      await apiClient.deleteProject(id)
      set((state) => ({
        projects: state.projects.filter((p) => p.id !== id),
        selectedProject:
          state.selectedProject?.id === id ? null : state.selectedProject,
        loading: false,
      }))
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete project',
        loading: false,
      })
    }
  },

  setSelectedProject: (project) => set({ selectedProject: project }),
  clearError: () => set({ error: null }),
}))
