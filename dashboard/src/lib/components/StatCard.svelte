<script lang="ts">
	let {
		label,
		value,
		hint,
		tone
	}: {
		label: string;
		value: string;
		hint?: string;
		tone?: 'ok' | 'bad' | 'warn';
	} = $props();
</script>

<div class="stat">
	<span class="label">{label}</span>
	<span class="value" style:color={tone === 'ok' ? 'var(--ok)' : tone === 'bad' ? 'var(--bad)' : tone === 'warn' ? 'var(--warn)' : undefined}>
		{value}
	</span>
	{#if hint}
		<span class="hint">{hint}</span>
	{/if}
</div>