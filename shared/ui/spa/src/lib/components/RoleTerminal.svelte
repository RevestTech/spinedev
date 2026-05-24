<script lang="ts">
  export interface TerminalLine {
    formatted?: string;
    message?: string;
    level?: string;
    ts?: number;
  }

  export let lines: TerminalLine[] = [];
  export let active = false;
  export let title = 'Activity log';
  export let emptyMessage = 'No activity yet. Output will appear here when a pipeline step runs.';

  let scroller: HTMLPreElement;

  $: if (scroller && lines.length) {
    queueMicrotask(() => {
      scroller.scrollTop = scroller.scrollHeight;
    });
  }

  function lineText(line: TerminalLine): string {
    return line.formatted || line.message || '';
  }

  function lineClass(line: TerminalLine): string {
    if (line.level === 'error') return 'text-rose-300';
    if (line.level === 'warn') return 'text-amber-200';
    if (line.level === 'success') return 'text-emerald-300';
    return 'text-emerald-100/90';
  }
</script>

<div
  class="role-terminal flex h-full min-h-[16rem] flex-col overflow-hidden rounded-lg border border-surface-700/80 bg-[#0a0f0d]"
  data-testid="role-terminal"
>
  <header
    class="flex shrink-0 items-center justify-between border-b border-surface-800/80 bg-[#0d1210] px-3 py-2"
  >
    <div class="flex items-center gap-2">
      <span class="inline-flex gap-1" aria-hidden="true">
        <span class="h-2.5 w-2.5 rounded-full bg-rose-500/80"></span>
        <span class="h-2.5 w-2.5 rounded-full bg-amber-400/80"></span>
        <span class="h-2.5 w-2.5 rounded-full bg-emerald-400/80"></span>
      </span>
      <span class="font-mono text-xs uppercase tracking-wide text-surface-400">{title}</span>
    </div>
    {#if active}
      <span class="inline-flex items-center gap-1.5 font-mono text-xs text-accent">
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"></span>
        In progress
      </span>
    {/if}
  </header>
  <pre
    bind:this={scroller}
    class="role-terminal-body min-h-0 flex-1 overflow-y-auto p-3 font-mono text-[0.8125rem] leading-relaxed"
    aria-live="polite"
    aria-relevant="additions"
  >
{#if lines.length === 0}
<span class="text-surface-500">{emptyMessage}</span>
{:else}
{#each lines as line, i (i)}
<span class="block whitespace-pre-wrap break-words {lineClass(line)}">{lineText(line)}</span>
{/each}
{/if}{#if active && lines.length > 0}
<span class="mt-1 inline-block h-4 w-2 animate-pulse bg-accent/80 align-middle" aria-hidden="true"></span>
{/if}
  </pre>
</div>

<style>
  .role-terminal-body {
    scrollbar-color: rgb(51 65 85 / 0.8) transparent;
  }
</style>
