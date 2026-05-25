<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import ProjectSubnav from '$lib/components/ProjectSubnav.svelte';
  import AuditPanel from '$lib/project-panels/AuditPanel.svelte';
  import { api } from '$lib/api/client';

  $: projectId = $page.params.project_id ?? '';
  let projectName = '';

  onMount(async () => {
    if (!projectId) return;
    try {
      const row = await api.get<{ name?: string }>(`/api/v2/projects/${encodeURIComponent(projectId)}`);
      projectName = row.name ?? projectId;
    } catch {
      projectName = projectId;
    }
  });
</script>

<ProjectSubnav {projectId} {projectName} active="audit" />
<AuditPanel {projectId} {projectName} />
