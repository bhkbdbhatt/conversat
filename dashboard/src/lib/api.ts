/**
 * Thin wrapper around the conversat API.
 *
 * Every call is relative (`/api/...`) so the same bundle works when FastAPI
 * serves the built app and when Vite proxies to `conversat serve` in dev.
 */
import type {
	CaseHistory,
	CaseResult,
	ConnectorInfo,
	CrawlSummary,
	CrawlTree,
	Health,
	ImportFormat,
	ImportResult,
	LiveSnapshot,
	RunOptions,
	RunReport,
	RunSummary,
	Stats,
	SuitePayload,
	SuiteSummary,
	TrendPoint,
	TurnRecord
} from './types';

export class ApiError extends Error {
	readonly status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetch(path, {
			...init,
			headers: {
				accept: 'application/json',
				...(init?.body ? { 'content-type': 'application/json' } : {}),
				...init?.headers
			}
		});
	} catch (cause) {
		throw new ApiError(
			'Cannot reach the conversat API. Is `conversat serve` running?',
			0
		);
	}

	if (!response.ok) {
		throw new ApiError(await describeFailure(response), response.status);
	}
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

async function describeFailure(response: Response): Promise<string> {
	try {
		const body = await response.json();
		const detail = body?.detail;
		if (typeof detail === 'string') return detail;
		if (Array.isArray(detail) && detail.length) {
			return detail
				.map((item: { loc?: string[]; msg?: string }) =>
					`${item.loc?.join('.') ?? ''} ${item.msg ?? ''}`.trim()
				)
				.join('; ');
		}
		return JSON.stringify(body);
	} catch {
		return `${response.status} ${response.statusText}`;
	}
}

function query(params: Record<string, string | number | undefined | null>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
	}
	const text = search.toString();
	return text ? `?${text}` : '';
}

export const api = {
	health: () => request<Health>('/api/health'),
	stats: () => request<Stats>('/api/stats'),
	trends: (limit = 30) => request<TrendPoint[]>(`/api/trends${query({ limit })}`),

	runs: () => request<RunSummary[]>('/api/runs'),
	run: (runId: string) => request<RunReport>(`/api/runs/${encodeURIComponent(runId)}`),
	runTurns: (runId: string) =>
		request<TurnRecord[]>(`/api/runs/${encodeURIComponent(runId)}/turns`),
	runCases: (runId: string) =>
		request<import('./types').CaseResult[]>(`/api/runs/${encodeURIComponent(runId)}/cases`),
	activeRuns: () => request<LiveSnapshot[]>('/api/runs/active'),
	startRun: (suites: string[], options: RunOptions = {}) =>
		request<{ started: LiveSnapshot[] }>('/api/runs', {
			method: 'POST',
			body: JSON.stringify({ suites, options })
		}),
	cases: () => request<import('./types').CaseRow[]>('/api/cases'),
	caseHistory: (name: string, limit = 25) =>
		request<CaseHistory[]>(`/api/cases/history${query({ name, limit })}`),

	suites: () => request<{ directory: string; suites: SuiteSummary[] }>('/api/suites'),
	suite: (name: string) => request<SuitePayload>(`/api/suites/${encodeURIComponent(name)}`),
	createSuite: (payload: unknown) =>
		request<SuitePayload>('/api/suites', { method: 'POST', body: JSON.stringify(payload) }),
	updateSuite: (name: string, payload: unknown) =>
		request<SuitePayload>(`/api/suites/${encodeURIComponent(name)}`, {
			method: 'PUT',
			body: JSON.stringify(payload)
		}),
	deleteSuite: (name: string) =>
		request<void>(`/api/suites/${encodeURIComponent(name)}`, { method: 'DELETE' }),

	/** Validate raw YAML text; the server parses it, so the browser needs no YAML lib. */
	validateYaml: (text: string) =>
		request<{ valid: boolean; errors: string[]; cases: string[]; tags?: string[] }>(
			'/api/suites/validate',
			{ method: 'POST', body: JSON.stringify({ yaml: text }) }
		),
	saveYaml: (text: string, name?: string) =>
		name
			? request<SuitePayload>(`/api/suites/${encodeURIComponent(name)}`, {
					method: 'PUT',
					body: JSON.stringify({ yaml: text })
				})
			: request<SuitePayload>('/api/suites', {
					method: 'POST',
					body: JSON.stringify({ yaml: text })
				}),

	crawls: () => request<CrawlSummary[]>('/api/crawl'),
	crawl: (crawlId: string) => request<CrawlTree>(`/api/crawl/${encodeURIComponent(crawlId)}`),

	/** Supported conversation-import formats. */
	importers: () => request<ImportFormat[]>('/api/importers'),
	detectImport: (content: string, filename?: string) =>
		request<{ format: string }>('/api/importers/detect', {
			method: 'POST',
			body: JSON.stringify({ content, filename })
		}),
	importConversation: (payload: {
		content: string;
		filename?: string;
		format?: string | null;
		name?: string;
		connector?: string;
		assertions?: 'contains' | 'exact' | 'none';
		tags?: string;
	}) => request<ImportResult>('/api/suites/import', { method: 'POST', body: JSON.stringify(payload) }),

	connectors: () => request<ConnectorInfo[]>('/api/connectors'),
	assertions: () => request<{ type: string }[]>('/api/assertions')
};

export function liveSocketUrl(runId: string): string {
	const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${protocol}//${location.host}/ws/runs/${encodeURIComponent(runId)}`;
}