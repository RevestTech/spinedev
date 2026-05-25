<!--
  Secondary nav for a single project: workspace + observe surfaces scoped to
  that project's UUID (KG, audit, ad-hoc role chat).
-->
<script lang="ts">
  import { base } from '$app/paths';
  import { page } from '$app/stores';

  export let projectId: string;
  export let projectName = 'Project';

  type SubnavId = 'workspace' | 'kg' | 'audit' | 'role-chat';

  const items: { id: SubnavId; suffix: string; label: string; testId: string }[] = [
    { id: 'workspace', suffix: '', label: 'Workspace', testId: 'subnav-workspace' },
    { id: 'kg', suffix: '/kg', label: 'Knowledge graph', testId: 'subnav-kg' },
    { id: 'audit', suffix: '/audit', label: 'Audit log', testId: 'subnav-audit' },
    { id: 'role-chat', suffix: '/role-chat', label: 'Talk to a role', testId: 'subnav-role-chat' }
  ];

  $: root = `${base}/projects/${encodeURIComponent(projectId)}`;
  $: pathname = $page.url.pathname.replace(/\/+$/, '') || '/';

  function hrefFor(suffix: string): string {
    return suffix ? `${root}${suffix}` : root;
  }

  function isActive(suffix: string): boolean {
    const target = hrefFor(suffix).replace(/\/+$/, '');
    if (!suffix) {
      return pathname === target;
    }
    return pathname === target || pathname.startsWith(`${target}/`);
  }

  export let active: SubnavId | null = null;

  $: resolvedActive =
    active ??
    (pathname.endsWith('/kg') || pathname.includes('/kg/')
      ? 'kg'
      : pathname.endsWith('/audit') || pathname.includes('/audit/')
        ? 'audit'
        : pathname.endsWith('/role-chat') || pathname.includes('/role-chat/')
          ? 'role-chat'
          : 'workspace');
</script>

<nav
  class="mb-5 flex flex-col gap-2 border-b border-surface-700/60 pb-3 sm:flex-row sm:items-center sm:justify-between"
  aria-label="Project sections"
  data-testid="project-subnav"
>
  <div class="min-w-0">
    <p class="text-xs uppercase tracking-wide text-surface-500">Project</p>
    <p class="truncate text-sm font-medium text-surface-200">{projectName}</p>
  </div>
  <ul class="flex flex-wrap gap-1">
    {#each items as item (item.id)}
      <li>
        <a
          href={hrefFor(item.suffix)}
          class="rounded-lg px-3 py-1.5 text-sm transition-colors {resolvedActive === item.id
            ? 'bg-accent/15 font-semibold text-accent'
            : 'text-surface-400 hover:bg-surface-800 hover:text-surface-100'}"
          aria-current={resolvedActive === item.id ? 'page' : undefined}
          data-testid={item.testId}
        >
          {item.label}
        </a>
      </li>
    {/each}
  </ul>
</nav>
