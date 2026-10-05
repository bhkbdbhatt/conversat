/**
 * Shapes returned by the conversat dashboard API.
 *
 * Kept hand-written rather than generated from the OpenAPI schema: the surface
 * is small and this file doubles as the contract the UI is built against.
 */

export type TurnStatus = 'passed' | 'failed' | 'error' | 'skipped';

export interface Totals {
	cases: number;
	cases_passed: number;
	cases_failed: number;
	cases_errored: number;
	cases_skipped: number;
	turns: number;
	turns_passed: number;
	assertions: number;
	assertions_passed: number;
	duration_ms: number;
	response_p50_ms: number;
	response_p95_ms: number;
}

export interface AssertionOutcome {
	type: string;
	description: string;
	passed: boolean;
	message: string | null;
	expected: string | null;
	actual: string | null;
	duration_ms: number | null;
}

export interface TurnRow {
	index: number;
	name: string | null;
	status: TurnStatus;
	request: string | null;
	reply: string | null;
	error: string | null;
	duration_ms: number;
	attempts: number;
	assertions: AssertionOutcome[];
}

export interface TurnRecord extends TurnRow {
	suite: string;
	case: string;
	tags: string[];
}

export interface CaseResult {
	name: string;
	status: TurnStatus;
	tags: string[];
	connector: string;
	turns: number;
	duration_ms: number;
	error: string | null;
	transcript: TurnRow[];
}

export interface CaseRow {
	run_id: string;
	suite: string;
	name: string;
	status: TurnStatus;
	tags: string[];
	turns: number;
	duration_ms: number;
}

export interface RunSummary {
	run_id: string;
	suite: string;
	connector: string;
	started_at: string;
	duration_ms: number;
	status: 'passed' | 'failed';
	labels: string[];
	totals: Totals;
}

export interface RunReport {
	run_id: string;
	suite: string;
	version: string;
	started_at: string;
	finished_at: string;
	connector: string;
	environment: Record<string, unknown>;
	labels: string[];
	cases: {
		name: string;
		status: TurnStatus;
		tags: string[];
		connector: string;
		turns: TurnRecord[];
		error: string | null;
	}[];
	totals: Totals;
}

export interface TrendPoint {
	run_id: string;
	suite: string;
	started_at: string;
	status: 'passed' | 'failed';
	pass_rate: number;
	cases: number;
	cases_passed: number;
	turns: number;
	assertions: number;
	duration_ms: number;
	p95_ms: number;
}

export interface Stats {
	runs: number;
	cases: number;
	failed_cases: number;
	assertions: number;
	avg_duration_ms: number;
}

export interface Health {
	status: string;
	version: string;
	runs: number;
	crawls: number;
	suites: number;
	reports_dir: string;
	suites_dir: string;
	ui: boolean;
	live: string[];
}

export interface SuiteSummary {
	name: string;
	path: string;
	document: number;
	description?: string | null;
	connector?: string;
	cases?: number;
	turns?: number;
	assertions?: number;
	tags?: string[];
	enabled?: number;
	modified?: string | null;
	error?: string | null;
}

export interface SuitePayload {
	name: string;
	description?: string | null;
	connector: ConnectorConfig;
	cases: CasePayload[];
	defaults?: Record<string, unknown>;
	variables?: Record<string, unknown>;
	metadata?: Record<string, unknown>;
	path?: string;
	document?: number;
	modified?: string | null;
	yaml?: string;
}

export interface ConnectorConfig {
	type: string;
	config?: Record<string, unknown>;
	name?: string | null;
}

export interface CasePayload {
	name: string;
	description?: string | null;
	tags?: string[];
	setup?: TurnPayload[];
	steps?: TurnPayload[];
	turns?: TurnPayload[];
	variables?: Record<string, unknown>;
	timeout?: number | null;
	retry?: Record<string, unknown> | null;
	connector?: ConnectorConfig | null;
	metadata?: Record<string, unknown>;
	enabled?: boolean;
}

export interface TurnPayload {
	send?: string | null;
	payload?: Record<string, unknown> | null;
	expect?: unknown[];
	name?: string | null;
	timeout?: number | null;
	retry?: Record<string, unknown> | null;
	clear_context?: boolean;
	metadata?: Record<string, unknown>;
}

export interface ConnectorInfo {
	type: string;
	description: string;
	builtin: boolean;
	defaults: Record<string, unknown>;
}

export interface CrawlSummary {
	crawl_id: string;
	suite: string;
	connector: string;
	started_at: string;
	duration_ms: number;
	nodes: number;
	max_depth: number;
	unique_responses: number;
	issues: number;
	suggested_cases: number;
	error_rate: number;
}

export interface CrawlNodeRow {
	id: string;
	parent: string | null;
	depth: number;
	request: string;
	reply: string | null;
	status: string;
	duration_ms: number;
	error: string | null;
	follow_ups: string[];
	children: string[];
}

export interface CrawlIssue {
	kind: string;
	severity: string;
	node_id: string;
	depth: number;
	message: string;
	request: string | null;
	response: string | null;
}

export interface CrawlTree {
	crawl_id: string;
	suite: string;
	connector: string;
	connector_config: Record<string, unknown>;
	started_at: string;
	finished_at: string;
	duration_ms: number;
	config: Record<string, unknown>;
	roots: string[];
	nodes: Record<string, CrawlNodeRow>;
	coverage: Record<string, number | boolean>;
	issues: CrawlIssue[];
	suggested_cases: unknown[];
	suite_yaml: Record<string, unknown>;
	ok: boolean;
}

export interface RunOptions {
	concurrency?: number;
	fail_fast?: boolean;
	tags?: string[];
	exclude_tags?: string[];
	cases?: string[];
	name_pattern?: string;
	timeout?: number;
	dry_run?: boolean;
	labels?: string[];
	variables?: Record<string, unknown>;
	connector?: string | ConnectorConfig;
}

export interface LiveSnapshot {
	run_id: string;
	suite: string;
	status: 'queued' | 'running' | 'passed' | 'failed' | 'error';
	started_at: string;
	finished_at: string | null;
	error: string | null;
	labels: string[];
	events: number;
	totals?: Totals;
	cases?: { name: string; status: TurnStatus; turns: number }[];
}

export type LiveEvent =
	| ({ type: 'snapshot' } & LiveSnapshot)
	| {
			type: 'status';
			run_id: string;
			status: string;
	  }
	| { type: 'replay'; run_id: string; status: string; finished: boolean; totals?: Totals }
	| {
			type: 'case_start';
			run_id: string;
			case: string;
			index: number;
			total: number;
	  }
	| ({ type: 'turn_result'; run_id: string; case: string } & TurnRow)
	| {
			type: 'case_end';
			run_id: string;
			case: string;
			status: TurnStatus;
			tags: string[];
			turns: number;
			duration_ms: number;
			error: string | null;
			assertions: number;
			failed: number;
	  }
	| { type: 'run_end'; run_id: string; totals: Totals; ok: boolean }
	| { type: 'done'; run_id: string; status: string; error: string | null }
	| { type: 'error'; error: string };

export interface CaseHistory {
	run_id: string;
	suite: string;
	started_at: string;
	status: TurnStatus;
	turns: number;
	assertions: number;
	failed_assertions: number;
	duration_ms: number;
	error: string | null;
	turn_rows: TurnRow[];
}

export interface ImportFormat {
	name: string;
	extensions: string[];
	description: string;
	example: string;
}

export interface ImportSummary {
	format: string;
	name: string;
	cases: number;
	turns: number;
	messages: number;
	assertions: number;
	connector: string;
	warnings: string[];
}

export interface ImportResult {
	format: string;
	summary: ImportSummary;
	warnings: string[];
	conversations: { name: string | null; messages: { role: string; text: string }[] }[];
	suite: SuitePayload;
	yaml: string;
}