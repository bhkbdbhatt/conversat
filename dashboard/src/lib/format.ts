/** Formatting and small shared helpers. */
import type { TurnStatus } from './types';

export function duration(ms: number | null | undefined): string {
	if (ms === null || ms === undefined) return '—';
	if (ms < 1) return '<1ms';
	if (ms < 1000) return `${Math.round(ms)}ms`;
	if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)}s`;
	const minutes = Math.floor(ms / 60_000);
	const seconds = Math.round((ms % 60_000) / 1000);
	return `${minutes}m ${seconds}s`;
}

export function percent(value: number | null | undefined, digits = 1): string {
	if (value === null || value === undefined || Number.isNaN(value)) return '—';
	return `${value.toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
	return value === null || value === undefined ? '—' : value.toLocaleString();
}

const RELATIVE: [limit: number, divisor: number, unit: Intl.RelativeTimeFormatUnit][] = [
	[60_000, 1000, 'second'],
	[3_600_000, 60_000, 'minute'],
	[86_400_000, 3_600_000, 'hour'],
	[2_592_000_000, 86_400_000, 'day']
];

export function relativeTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	const then = new Date(iso).getTime();
	if (Number.isNaN(then)) return '—';
	const delta = Date.now() - then;
	if (delta < 5_000) return 'just now';
	const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
	for (const [limit, divisor, unit] of RELATIVE) {
		if (delta < limit) return formatter.format(-Math.round(delta / divisor), unit);
	}
	return new Date(iso).toLocaleDateString();
}

export function dateTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	const parsed = new Date(iso);
	return Number.isNaN(parsed.getTime())
		? iso
		: parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
}

export function isProblem(status: TurnStatus | string | undefined): boolean {
	return status === 'failed' || status === 'error';
}

export function statusTone(status: string | undefined): string {
	switch (status) {
		case 'passed':
			return 'ok';
		case 'failed':
		case 'error':
			return 'bad';
		case 'skipped':
			return 'muted';
		case 'running':
		case 'queued':
			return 'busy';
		default:
			return 'muted';
	}
}

export function truncate(text: string | null | undefined, limit: number): string {
	if (!text) return '';
	return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

export function oneLine(text: string | null | undefined): string {
	return (text ?? '').replace(/\s+/g, ' ').trim();
}

export function pluralise(count: number, singular: string, plural = `${singular}s`): string {
	return `${count} ${count === 1 ? singular : plural}`;
}

/** Collapse a long assertion/expectation value into something readable. */
export function describeExpectation(value: unknown): string {
	if (value === null || value === undefined) return '—';
	if (Array.isArray(value)) return value.map(describeExpectation).join(', ');
	if (typeof value === 'object') return JSON.stringify(value);
	return String(value);
}