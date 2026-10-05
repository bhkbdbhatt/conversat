<script lang="ts">
	import StatusBadge from './StatusBadge.svelte';
	import Transcript from './Transcript.svelte';
	import { duration, pluralise } from '$lib/format';
	import type { CaseResult } from '$lib/types';

	let {
		result,
		defaultOpen = false
	}: {
		result: CaseResult;
		defaultOpen?: boolean;
	} = $props();

	const failures = $derived(
		result.transcript.reduce((total, turn) => total + turn.assertions.filter((a) => !a.passed).length, 0)
	);
	const failedTurns = $derived(result.transcript.filter((t) => t.status !== 'passed').length);
</script>

<details class="disclosure" open={defaultOpen || result.status !== 'passed'}>
	<summary>
		<StatusBadge status={result.status} />
		<strong>{result.name}</strong>
		<span class="faint small">
			{pluralise(result.transcript.length, 'turn')}
			· {duration(result.duration_ms)}
			{#if failures}· <span style="color: var(--bad)">{failures} failed assertion{failures === 1 ? '' : 's'}</span>{/if}
			{#if failedTurns && !failures}· {failedTurns} non-passing turn{failedTurns === 1 ? '' : 's'}{/if}
		</span>
		<span class="grow" style="flex: 1"></span>
		{#each result.tags as tag (tag)}
			<span class="tag">{tag}</span>
		{/each}
		<span class="faint small mono">{result.connector}</span>
	</summary>
	<div class="disclosure-body">
		{#if result.error}
			<div class="notice bad" style="margin-bottom: 0.75rem">{result.error}</div>
		{/if}
		<div class="transcript">
			{#each result.transcript as turn (turn.index)}
				<Transcript {turn} />
			{/each}
		</div>
	</div>
</details>