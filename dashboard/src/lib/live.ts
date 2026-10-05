/** Subscribe to a run's progress WebSocket with automatic reconnects. */
import { liveSocketUrl } from './api';
import type { LiveEvent } from './types';

export function followRun(
	runId: string,
	onEvent: (event: LiveEvent) => void,
	{ onClose }: { onClose?: (reason: string) => void } = {}
): () => void {
	let socket: WebSocket | null = null;
	let closed = false;
	let retry: ReturnType<typeof setTimeout> | undefined;
	let attempts = 0;

	function connect() {
		socket = new WebSocket(liveSocketUrl(runId));

		socket.onmessage = (message) => {
			attempts = 0;
			try {
				onEvent(JSON.parse(message.data) as LiveEvent);
			} catch {
				// A malformed frame is not worth tearing the view down for.
			}
		};

		socket.onerror = () => socket?.close();

		socket.onclose = () => {
			if (closed) return;
			// The server closes the socket when the run finishes; reconnecting
			// then is pointless, so back off and retry only briefly.
			attempts += 1;
			if (attempts > 5) {
				onClose?.('connection lost');
				return;
			}
			retry = setTimeout(connect, Math.min(4000, 250 * 2 ** attempts));
		};
	}

	connect();

	return () => {
		closed = true;
		if (retry) clearTimeout(retry);
		socket?.close();
	};
}