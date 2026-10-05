<script lang="ts">
	import type { AssertionOutcome } from '$lib/types';
	import { duration, truncate } from '$lib/format';

	let { assertions }: { assertions: AssertionOutcome[] } = $props();

	const failures = $derived(assertions.filter((a) => !a.passed).length);
</script>

{#if assertions.length}
	<div class="assertions">
		{#each assertions as assertion, index (index)}
			<div class="assertion" class:failed={!assertion.passed}>
				<span class="type">{assertion.passed ? '✓' : '✗'}</span>
				<span class="type">{assertion.type}</span>
				<span class="detail">
					{assertion.message ?? assertion.description}
					{#if assertion.expected !== null || assertion.actual !== null}
						<span class="faint">
							· expected {truncate(assertion.expected ?? '—', 48)}
							· actual {truncate(assertion.actual ?? '—', 48)}
						</span>
					{/if}
				</span>
				{#if assertion.duration_ms !== null && assertion.duration_ms >= 1}
					<span class="detail faint">{duration(assertion.duration_ms)}</span>
				{/if}
			</div>
		{/each}
	</div>
{/if}

{#if failures}
	<span class="sr-only">{failures} failed assertions</span>
{/if}