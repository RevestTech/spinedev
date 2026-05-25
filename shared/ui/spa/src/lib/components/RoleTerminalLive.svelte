<script lang="ts">
  import RoleTerminal from '$lib/components/RoleTerminal.svelte';
  import { wsTerminal } from '$lib/stores/projectWorkspace';

  export let active = false;
  export let title = 'Activity log';
  export let emptyMessage =
    'No activity yet. Output will appear here when a pipeline step runs.';
</script>

<RoleTerminal lines={$wsTerminal} {active} {title} {emptyMessage} />
