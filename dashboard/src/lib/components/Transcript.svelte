<script lang="ts">
	import AssertionList from './AssertionList.svelte';
	import { duration } from '$lib/format';
	import type { TurnRow } from '$lib/types';

	let {
		turn,
		pending = false
	}: {
		turn: TurnRow;
		pending?: boolean;
	} = $props();

	const failed = $derived(turn.assertions.some((a) => !a.passed));
	const errored = $derived(turn.status === 'error' || Boolean(turn.error));
</script>

<div class="turn" class:bad={failed || errored}>
	<div class="turn-head">
		<span class="name">#{turn.index + 1}{turn.name ? ` · ${turn.name}` : ''}</span>
		<span class="badge" class:ok={turn.status === 'passed'} class:bad={turn.status === 'failed' || turn.status === 'error'} class:muted={turn.status === 'skipped'}>
			{pending ? 'running' : turn.status}
		</span>
		{#if turn.assertions.length}
			<span class="faint">
				{turn.assertions.filter((a) => a.passed).length}/{turn.assertions.length} assertions
			</span>
		{/if}
		<span class="grow"></span>
		{#if turn.attempts > 1}
			<span class="badge warn">{turn.attempts} attempts</span>
		{/if}
		<span title="turn duration">{duration(turn.duration_ms)}</span>
	</div>

	{#if turn.request}
		<div class="bubble-row">
			<span class="bubble-who">user</span>
			<div class="bubble user">{turn.request}</div>
		</div>
	{/if}

	<div class="bubble-row">
		<span class="bubble-who">bot</span>
		{#if pending && !turn.reply}
			<div class="bubble bot empty-reply"><span class="spinner"></span>waiting for a reply…</div>
		{:else if turn.reply}
			<div class="bubble bot">{turn.reply}</div>
		{:else}
			<div class="bubble bot empty-reply">&lt;no reply&gt;</div>
		{/if}
	</div>

	{#if turn.error}
		<div class="turn-error">{turn.error}</div>
	{/if}

	<AssertionList assertions={turn.assertions} />
</div>