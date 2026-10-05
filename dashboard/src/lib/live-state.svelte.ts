/**
 * Live run state machine.
 *
 * A `.svelte.ts` module so the reducer can own `$state` fields and be shared by
 * the `/live` list and the `/live/[id]` view without duplicating the event
 * handling. The WebSocket replays buffered events on connect, so a page opened
 * mid-run catches up immediately.
 */
import { followRun } from './live';
import { api } from './api';
import type { LiveEvent, TurnRow } from './types';

export interface LiveCase {
	name: string;
	status: string;
	turns: TurnRow[];
	error: string | null;
}

export type Connection = 'connecting' | 'open' | 'closed';

export class LiveRunView {
	runId = $state('');
	suite = $state('');
	status = $state<string>('queued');
	error = $state<string | null>(null);
	totals = $state<Record<string, number> | null>(null);
	cases = $state<LiveCase[]>([]);
	events = $state(0);
	connection = $state<Connection>('connecting');

	#stop: (() => void) | null = null;

	get active(): boolean {
		return this.status === 'queued' || this.status === 'running';
	}

	get completedCases(): number {
		return this.cases.filter((item) => item.status !== 'running').length;
	}

	get failedTurns(): number {
		return this.cases.reduce(
			(total, item) =>
				total + item.turns.filter((turn) => turn.status !== 'passed').length,
			0
		);
	}

	watch(runId: string): void {
		this.stop();
		this.reset(runId);
		this.connection = 'connecting';
		this.#stop = followRun(runId, (event) => this.handle(event), {
			onClose: () => {
				this.connection = 'closed';
			}
		});
	}

	stop(): void {
		this.#stop?.();
		this.#stop = null;
	}

	reset(runId: string): void {
		this.runId = runId;
		this.suite = '';
		this.status = 'queued';
		this.error = null;
		this.totals = null;
		this.cases = [];
		this.events = 0;
	}

	/** Fill in the suite name once the report exists on disk. */
	async refreshMeta(): Promise<void> {
		if (!this.runId) return;
		try {
			const report = await api.run(this.runId);
			this.suite = report.suite;
			this.totals = report.totals as unknown as Record<string, number>;
		} catch {
			// Not written yet; the socket carries everything we need meanwhile.
		}
	}

	handle(event: LiveEvent): void {
		this.events += 1;
		switch (event.type) {
			case 'snapshot':
				this.status = event.status;
				this.suite = event.suite;
				this.error = event.error;
				if (event.totals) this.totals = event.totals as unknown as Record<string, number>;
				break;
			case 'replay':
				this.status = event.status;
				if (event.totals) this.totals = event.totals as unknown as Record<string, number>;
				break;
			case 'status':
				this.status = event.status;
				break;
			case 'case_start':
				this.upsert(event.case).status = 'running';
				break;
			case 'turn_result':
				this.recordTurn(event.case, {
					index: event.index,
					name: event.name,
					status: event.status,
					request: event.request,
					reply: event.reply,
					error: event.error,
					duration_ms: event.duration_ms,
					attempts: event.attempts,
					assertions: event.assertions
				});
				break;
			case 'case_end': {
				const item = this.upsert(event.case);
				item.status = event.status;
				item.error = event.error;
				break;
			}
			case 'run_end':
				this.status = event.ok ? 'passed' : 'failed';
				this.totals = event.totals as unknown as Record<string, number>;
				break;
			case 'done':
				this.status = event.status;
				this.error = event.error;
				this.connection = 'closed';
				break;
			case 'error':
				this.error = event.error;
				this.connection = 'closed';
				break;
		}
	}

	upsert(name: string): LiveCase {
		const found = this.cases.find((item) => item.name === name);
		if (found) return found;
		const created: LiveCase = { name, status: 'running', turns: [], error: null };
		this.cases.push(created);
		return created;
	}

	recordTurn(caseName: string, row: TurnRow): void {
		const item = this.upsert(caseName);
		const index = item.turns.findIndex((turn) => turn.index === row.index);
		if (index >= 0) item.turns[index] = row;
		else item.turns.push(row);
	}
}