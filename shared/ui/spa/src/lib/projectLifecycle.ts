import { api } from '$lib/api/client';

export interface ProjectRecord {
  id?: number;
  project_id: string;
  project_uuid?: string;
  name: string;
  project_type?: string;
  current_phase?: string;
  status: string;
  owner?: string;
  metadata?: Record<string, unknown>;
  description?: string;
}

export interface ProjectPatchBody {
  name?: string;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

export async function updateProject(projectId: string, body: ProjectPatchBody): Promise<ProjectRecord> {
  return api.patch<ProjectRecord>(`/api/v2/projects/${projectId}`, body);
}

export async function archiveProject(projectId: string, note?: string): Promise<ProjectRecord> {
  return api.post<ProjectRecord>(`/api/v2/projects/${projectId}/archive`, note ? { note } : {});
}

export async function restoreProject(projectId: string, note?: string): Promise<ProjectRecord> {
  return api.post<ProjectRecord>(`/api/v2/projects/${projectId}/restore`, note ? { note } : {});
}

export async function deleteProject(projectId: string): Promise<{ ok: boolean; project_id: string }> {
  return api.delete<{ ok: boolean; project_id: string }>(`/api/v2/projects/${projectId}`);
}

export function projectBrief(project: Pick<ProjectRecord, 'metadata'>): string {
  const md = project.metadata ?? {};
  const desc = md.description;
  return typeof desc === 'string' ? desc : '';
}

export function isArchived(project: Pick<ProjectRecord, 'status'>): boolean {
  return project.status === 'completed';
}
