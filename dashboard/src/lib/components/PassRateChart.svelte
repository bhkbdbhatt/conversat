<script lang="ts">
	import { percent } from '$lib/format';
	import type { TrendPoint } from '$lib/types';

	let { points }: { points: TrendPoint[] } = $props();

	const WIDTH = 600;
	const HEIGHT = 48;
	const PAD = 4;

	interface Bar {
		x: number;
		y: number;
		w: number;
		h: number;
		point: TrendPoint;
	}

	const bars = $derived.by(() => {
		if (!points.length) return [] as Bar[];
		const step = (WIDTH - PAD * 2) / points.length;
		const width = Math.max(2, Math.min(28, step - 3));
		return points.map((point, index) => {
			const rate = Math.max(0, Math.min(100, point.pass_rate));
			const height = Math.max(2, ((HEIGHT - PAD * 2) * rate) / 100);
			return {
				x: PAD + index * step + (step - width) / 2,
				y: HEIGHT - PAD - height,
				w: width,
				h: height,
				point
			};
		});
	});

	const last = $derived(points.at(-1));
</script>

{#if !points.length}
	<div class="empty small">No runs recorded yet.</div>
{:else}
	<svg class="sparkline" viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" role="img"
		aria-label="pass rate across {points.length} runs">
		{#each bars as bar (bar.point.run_id)}
			<a href="/runs/{bar.point.run_id}" title={`${bar.point.suite} — ${percent(bar.point.pass_rate)} (${bar.point.cases_passed}/${bar.point.cases} cases)`}>
				<rect
					x={bar.x}
					y={bar.y}
					width={bar.w}
					height={bar.h}
					rx="2"
					fill={bar.point.status === 'passed' ? 'var(--ok)' : 'var(--bad)'}
					opacity="0.85"
				/>
			</a>
		{/each}
	</svg>
	<div class="legend">
		<span style="color: var(--ok)">pass rate</span>
		<span class="faint">
			{points.length} run{points.length === 1 ? '' : 's'}
			{#if last}· latest {percent(last.pass_rate)}{/if}
		</span>
	</div>
{/if}