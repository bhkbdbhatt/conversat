<script lang="ts">
	import CrawlNode from './CrawlNode.svelte';
	import type { CrawlNodeRow } from '$lib/types';
	import { statusTone, truncate } from '$lib/format';

	let {
		node,
		nodes,
		depth = 0
	}: {
		node: CrawlNodeRow;
		nodes: Record<string, CrawlNodeRow>;
		depth?: number;
	} = $props();
</script>

<div class="tree-node" style:margin-left={depth === 0 ? '0' : undefined}>
	<div class="row" style="gap: 0.5rem; align-items: baseline">
		<span class="badge {statusTone(node.status)} dot">{node.status}</span>
		<span class="tree-req" title={node.request}>{truncate(node.request, 70)}</span>
		<span class="grow" style="flex: 1"></span>
		<span class="faint small mono">{node.duration_ms.toFixed(0)}ms</span>
	</div>
	<div class="tree-reply" title={node.reply ?? ''}>{truncate(node.reply ?? '<no reply>', 110)}</div>
	{#if node.error}
		<div class="tree-reply" style="color: var(--bad)">{node.error}</div>
	{/if}
	{#if node.children.length}
		{#each node.children as childId (childId)}
			{#if nodes[childId]}
				<CrawlNode node={nodes[childId]} {nodes} depth={depth + 1} />
			{/if}
		{/each}
	{/if}
</div>