<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, ApiError } from '$lib/api';
	import type { ImportFormat, ImportResult } from '$lib/types';

	let formats = $state<ImportFormat[]>([]);
	let content = $state('');
	let filename = $state('');
	let format = $state<string>(''); // '' = auto-detect
	let name = $state('');
	let connector = $state('');
	let assertions = $state<'contains' | 'exact' | 'none'>('contains');
	let tags = $state('imported');

	let result = $state<ImportResult | null>(null);
	let detected = $state<string | null>(null);
	let busy = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let dragging = $state(false);
	let fileInput: HTMLInputElement | undefined = $state();

	$effect(() => {
		api
			.importers()
			.then((rows) => (formats = rows))
			.catch((cause) => (error = cause instanceof Error ? cause.message : String(cause)));
	});

	const MAX_BYTES = 20 * 1024 * 1024;
	const canConvert = $derived(content.trim().length > 0 && !busy);

	async function readFile(file: File) {
		if (file.size > MAX_BYTES) {
			error = `${file.name} is ${formatBytes(file.size)} — the limit is ${formatBytes(MAX_BYTES)}.`;
			return;
		}
		filename = file.name;
		content = await file.text();
		error = null;
		result = null;
		void detect();
	}

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	}

	async function detect() {
		detected = null;
		if (!content.trim()) return;
		try {
			detected = (await api.detectImport(content, filename || undefined)).format;
		} catch {
			// A failed sniff is not worth reporting here; Convert shows the error.
		}
	}

	let debounce: ReturnType<typeof setTimeout> | undefined;
	function onInput() {
		result = null;
		if (debounce) clearTimeout(debounce);
		debounce = setTimeout(() => void detect(), 600);
	}

	async function convert() {
		if (!content.trim()) return;
		busy = true;
		error = null;
		try {
			result = await api.importConversation({
				content,
				filename: filename || undefined,
				format: format || null,
				name: name || undefined,
				connector: connector || undefined,
				assertions,
				tags
			});
		} catch (cause) {
			result = null;
			error =
				cause instanceof ApiError && cause.status === 400
					? cause.message
					: `Import failed: ${cause instanceof Error ? cause.message : String(cause)}`;
		} finally {
			busy = false;
		}
	}

	async function save() {
		if (!result) return;
		saving = true;
		error = null;
		try {
			const saved = await api.saveYaml(result.yaml);
			await goto(`/suites/${encodeURIComponent(saved.name)}`);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			saving = false;
		}
	}

	const SAMPLES: { label: string; filename: string; content: string }[] = [
		{
			label: 'JSON',
			filename: 'chat.json',
			content: `[
  { "role": "user", "content": "Hi, I need help with my order" },
  { "role": "assistant", "content": "Of course! Can you share your order number?" },
  { "role": "user", "content": "It's 44821" },
  { "role": "assistant", "content": "Thanks Ada. Order 44821 arrives on Friday." }
]`
		},
		{
			label: 'CSV',
			filename: 'tickets.csv',
			content: `case,role,text
greeting,customer,Hello
greeting,support,"Hi there, how can I help?"
refund,customer,I want a refund
refund,support,Refunds are available within 30 days of purchase.`
		},
		{
			label: 'Markdown',
			filename: 'chat.md',
			content: `# Password reset

**User:** I can't log in

**Bot:** Did you use the "forgot password" link?

**User:** Yes, but no email arrives

**Bot:** Check your spam folder and whitelist support@example.com.`
		},
		{
			label: 'Plain text',
			filename: 'chat.txt',
			content: `User: Hello there
Bot: Hi! How can I help?

User: What are your hours?
Bot: We are open 9 to 5 on weekdays.`
		},
		{
			label: 'XML',
			filename: 'tickets.xml',
			content: `<supportdesk>
  <message author="customer">The checkout page is blank</message>
  <message author="agent">Try a hard refresh with Ctrl+Shift+R.</message>
</supportdesk>`
		}
	];

	function loadSample(sample: (typeof SAMPLES)[number]) {
		filename = sample.filename;
		content = sample.content;
		format = '';
		result = null;
		error = null;
		void detect();
	}

	const chosen = $derived(detected ?? format);
</script>

<svelte:head><title>conversat — import a conversation</title></svelte:head>

<div class="page-head">
	<div class="grow">
		<h1>Import a conversation</h1>
		<p>
			Turn a chat export into a runnable suite. The captured replies become a
			<code class="mono">scripted</code> connector, so the result is a golden-transcript test: it
			passes now and fails the moment the bot's answers drift.
		</p>
	</div>
	<a class="button" href="/suites">all suites</a>
</div>

<div class="grid" style="grid-template-columns: minmax(0, 1fr) minmax(300px, 420px); align-items: start">
	<div class="stack">
		<div class="panel">
			<div class="panel-head">
				<h2>1 · Paste or drop the export</h2>
				{#if chosen}
					<span class="badge {result ? 'ok' : 'busy'} dot">{chosen}</span>
				{/if}
			</div>
			<div class="panel-body">
				<div
					class="dropzone"
					class:dragging
					role="button"
					tabindex="0"
					onclick={() => fileInput?.click()}
					onkeydown={(event) => (event.key === 'Enter' || event.key === ' ') && fileInput?.click()}
					ondragover={(event) => {
						event.preventDefault();
						dragging = true;
					}}
					ondragleave={() => (dragging = false)}
					ondrop={(event) => {
						event.preventDefault();
						dragging = false;
						const file = event.dataTransfer?.files?.[0];
						if (file) void readFile(file);
					}}
				>
					<strong>Drop a file here</strong>
					<span class="muted small">
						or click to browse — {formats.length} formats supported, up to
						{formatBytes(MAX_BYTES)}
					</span>
					<input
						bind:this={fileInput}
						type="file"
						class="visually-hidden"
						onchange={(event) => {
							const file = event.currentTarget.files?.[0];
							if (file) void readFile(file);
						}}
					/>
				</div>

				{#if filename}
					<div class="row" style="margin: 0.75rem 0">
						<span class="tag">{filename}</span>
						<span class="faint small">{formatBytes(new Blob([content]).size)}</span>
						<button class="ghost" onclick={() => ((content = ''), (filename = ''), (result = null))}>
							clear
						</button>
					</div>
				{/if}

				<textarea
					bind:value={content}
					oninput={onInput}
					spellcheck="false"
					rows="14"
					placeholder={'User: Hello\nBot: Hi there, how can I help?'}
					aria-label="Conversation export"
				></textarea>

				<div class="row" style="margin-top: 0.6rem">
					<span class="faint small">try:</span>
					{#each SAMPLES as sample (sample.label)}
						<button class="ghost" onclick={() => loadSample(sample)}>{sample.label}</button>
					{/each}
				</div>
			</div>
		</div>

		{#if result}
			<div class="panel">
				<div class="panel-head">
					<h2>3 · Review</h2>
					<span class="badge ok dot">
						{result.summary.cases} case(s) · {result.summary.turns} turn(s)
					</span>
					<span class="grow" style="flex: 1"></span>
					<button class="primary" onclick={save} disabled={saving}>
						{saving ? 'Saving…' : 'Save suite'}
					</button>
				</div>
				<div class="panel-body stack">
					{#if result.warnings.length}
						<div class="notice warn">
							<ul style="margin: 0; padding-left: 1.1rem">
								{#each result.warnings as warning (warning)}
									<li>{warning}</li>
								{/each}
							</ul>
						</div>
					{/if}

					<div>
						<h3 style="margin-bottom: 0.4rem">Parsed conversations</h3>
						<div class="stack">
							{#each result.conversations as conversation, i (i)}
								<details class="disclosure" open={i === 0}>
									<summary>
										<strong>{conversation.name ?? `conversation ${i + 1}`}</strong>
										<span class="faint small">{conversation.messages.length} message(s)</span>
									</summary>
									<div class="disclosure-body">
										<div class="transcript">
											{#each conversation.messages as message, j (j)}
												<div class="bubble-row">
													<span class="bubble-who">{message.role}</span>
													<div class="bubble {message.role}">{message.text}</div>
												</div>
											{/each}
										</div>
									</div>
								</details>
							{/each}
						</div>
					</div>

					<div>
						<h3 style="margin-bottom: 0.4rem">Generated suite</h3>
						<pre>{result.yaml}</pre>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<div class="stack">
		<div class="panel">
			<div class="panel-head"><h2>2 · Options</h2></div>
			<div class="panel-body">
				<div class="field">
					<label for="imp-format">Input format</label>
					<select id="imp-format" bind:value={format}>
						<option value="">detect automatically</option>
						{#each formats as item (item.name)}
							<option value={item.name}>{item.name} — {item.description}</option>
						{/each}
					</select>
					{#if detected && !format}
						<span class="faint small">detected: {detected}</span>
					{/if}
				</div>

				<div class="field">
					<label for="imp-name">Suite name</label>
					<input
						id="imp-name"
						placeholder={filename ? filename.replace(/\.[^.]+$/, '') : 'from the filename'}
						bind:value={name}
					/>
				</div>

				<div class="field">
					<label for="imp-assertions">Generated assertions</label>
					<select id="imp-assertions" bind:value={assertions}>
						<option value="contains">contains a fragment of the reply</option>
						<option value="exact">match the reply exactly</option>
						<option value="none">only check for a non-empty reply</option>
					</select>
				</div>

				<div class="field">
					<label for="imp-connector">Connector (optional)</label>
					<input
						id="imp-connector"
						placeholder="http:url=http://127.0.0.1:8099/chat"
						bind:value={connector}
					/>
					<span class="faint small">
						leave empty to replay the captured replies with the <code>scripted</code> connector
					</span>
				</div>

				<div class="field">
					<label for="imp-tags">Tags</label>
					<input id="imp-tags" bind:value={tags} />
				</div>

				<button class="primary" onclick={convert} disabled={!canConvert} style="width: 100%">
					<span class:spinner={busy}></span>
					{busy ? 'Converting…' : 'Convert to suite'}
				</button>

				{#if error}
					<div class="notice bad" style="margin-top: 0.75rem">{error}</div>
				{/if}
			</div>
		</div>

		<div class="panel">
			<div class="panel-head"><h3>Supported formats</h3></div>
			<div class="panel-body flush">
				{#if !formats.length}
					<div class="loading"><span class="spinner"></span>loading…</div>
				{:else}
					<table>
						<tbody>
							{#each formats as item (item.name)}
								<tr>
									<td class="mono nowrap"><strong>{item.name}</strong></td>
									<td class="small muted">
										{item.description}
										{#if item.extensions.length}
											<div class="faint mono" style="margin-top: 0.15rem">
												{item.extensions.join(' ')}
											</div>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.dropzone {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.2rem;
		padding: 1.5rem 1rem;
		border: 1px dashed var(--border-strong);
		border-radius: var(--radius);
		background: var(--bg-sunken);
		cursor: pointer;
		margin-bottom: 0.75rem;
	}

	.dropzone:hover,
	.dropzone.dragging {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 8%, var(--bg-sunken));
	}

	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	textarea {
		min-height: 16rem;
	}
</style>