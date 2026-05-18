<!--
  Spine Hub SPA — CitationChip (V3 Wave 3 part 2, Squad SPA1).

  Per design decision #12 (Cite-or-Refuse): every cite-required response
  from a verify-class role MUST render its supporting evidence inline.
  This chip is the canonical surface — both the decision-queue panel and
  the role-chat panel render an array of <CitationChip /> below the body.

  The three Citation types (per shared/mcp/schemas/envelopes.py:Citation)
  map to distinct visual treatments so the user can scan provenance at
  a glance:

    - kg_node    → blue chip, links to /panels/kg-search?node=<ref> (SPA2)
    - file_line  → emerald chip, links to /panels/audit?file=<ref> (SPA2)
    - audit_hash → indigo chip, links to /panels/audit?hash=<ref> (SPA2)

  Until SPA2 ships those panels, the chip renders as a static tooltip — no
  broken links — but the IA already exists for the click-through.
-->
<script lang="ts">
  import type { Citation } from '$lib/api/types';
  export let citation: Citation;

  const palette: Record<Citation['type'], { ring: string; bg: string; text: string; label: string }> = {
    kg_node: {
      ring: 'ring-severity-info/40',
      bg: 'bg-severity-info/10',
      text: 'text-blue-900 dark:text-blue-100',
      label: 'KG'
    },
    file_line: {
      ring: 'ring-emerald-300',
      bg: 'bg-emerald-50',
      text: 'text-emerald-900 dark:text-emerald-100',
      label: 'FILE'
    },
    audit_hash: {
      ring: 'ring-indigo-300',
      bg: 'bg-indigo-50',
      text: 'text-indigo-900 dark:text-indigo-100',
      label: 'AUDIT'
    }
  };

  $: tone = palette[citation.type] ?? palette.kg_node;
  $: title = citation.excerpt ? `${citation.ref}\n\n${citation.excerpt}` : citation.ref;
</script>

<span
  class="inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-xs ring-1 {tone.ring} {tone.bg} {tone.text}"
  title={title}
  data-citation-type={citation.type}
>
  <span class="font-mono text-[0.6rem] uppercase tracking-wide opacity-80">{tone.label}</span>
  <span class="truncate font-mono text-[0.7rem]">{citation.ref}</span>
</span>
