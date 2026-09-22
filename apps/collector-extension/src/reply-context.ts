const BACKEND = 'http://127.0.0.1:8787';
const OWNER_KEY = 'crr_context_owned_tab';
const LIMITS = { requestMs: 8000, pageMs: 18000, depth: 3, text: 12000 };
interface ContextNode { tweet_id: string; author: string; text: string; posted_at: string; parent_id: string | null; relation_source: string; completeness: string; language: string }
interface Owner { tabId: number; url: string }
let running = false;

async function api(path: string, payload?: unknown): Promise<any> {
  const response = await fetch(BACKEND + path, { method: payload === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload),
    signal: AbortSignal.timeout(LIMITS.requestMs) });
  if (!response.ok) throw new Error('BACKEND_UNAVAILABLE');
  return response.json();
}

async function owned(owner: Owner): Promise<boolean> {
  const tab = await chrome.tabs.get(owner.tabId).catch(() => undefined);
  return Boolean(tab && [tab.url,tab.pendingUrl].some(value => {
    if (!value) return false;
    const expected = new URL(owner.url), actual = new URL(value);
    return actual.origin === expected.origin && actual.pathname.match(/\/status\/(\d+)/)?.[1] === expected.pathname.match(/\/status\/(\d+)/)?.[1]
      && actual.searchParams.get('crr_context') === expected.searchParams.get('crr_context');
  }));
}

async function detail(id: string): Promise<ContextNode> {
  if (!/^\d{1,25}$/.test(id)) throw new Error('RELATION_UNCONFIRMED');
  const stored = (await chrome.storage.local.get(OWNER_KEY))[OWNER_KEY] as Owner | undefined;
  if (stored && !await owned(stored)) {
    await chrome.storage.local.remove(OWNER_KEY);
    throw new Error('USER_NAVIGATED');
  }
  const url = `https://x.com/i/status/${id}?crr_context=${crypto.randomUUID()}`;
  const tab = stored ? await chrome.tabs.update(stored.tabId, { url, active: false }) : await chrome.tabs.create({ url, active: false });
  if (!tab.id) throw new Error('BROWSER_DISCONNECTED');
  const owner = { tabId: tab.id, url };
  await chrome.storage.local.set({ [OWNER_KEY]: owner });
  const end = Date.now() + LIMITS.pageMs;
  while (Date.now() < end) {
    const current = await chrome.tabs.get(tab.id).catch(()=>undefined);
    if (current?.url?.includes('/i/flow/login')) throw new Error('LOGIN_REQUIRED');
    if (!await owned(owner)) throw new Error('USER_NAVIGATED');
    const result = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN',
      func: (tid: string) => {
        const capture = (window as unknown as { __crrContext?: Record<string, unknown> }).__crrContext;
        return { node: capture?.[tid] ?? null, login: location.pathname.startsWith('/i/flow/login'),
          error: (window as unknown as { __crrContextError?: string }).__crrContextError };
      }, args: [id] }).catch(() => []);
    const value = result[0]?.result;
    if (value?.login) throw new Error('LOGIN_REQUIRED');
    if (value?.node) return value.node as ContextNode;
    if (value?.error) throw new Error(value.error);
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  throw new Error('PAGE_LOADING');
}

export async function runReplyContext(): Promise<void> {
  if (running) return;
  running = true;
  try {
    const { job } = await api('/api/v2/context/claim', {});
    if (!job) return;
    const nodes: ContextNode[] = [];
    let reason: string | undefined;
    try {
      let id: string | null = job.tweet_id;
      for (let level = 0; id && level <= LIMITS.depth; level++) {
        const cached = (await api(`/api/v2/context/cache/${id}`)).node;
        if (cached?.restricted) throw new Error('INCOMPLETE_CONTENT');
        const node: ContextNode = cached && (level>0 || cached.relation_source==='x_replied_to_field') ? cached : await detail(id);
        if (node.tweet_id !== id || nodes.some(n => n.tweet_id === id)) throw new Error('RELATION_UNCONFIRMED');
        if (nodes.reduce((size,n) => size+n.text.length,0)+node.text.length>LIMITS.text) throw new Error('INCOMPLETE_CONTENT');
        nodes.push(node);
        id = node.parent_id;
      }
    } catch (error) { reason = error instanceof Error ? error.message : 'NETWORK_OR_RATE_LIMIT'; }
    await api('/api/v2/context/result', { id: job.id, lease: job.lease, nodes, reason });
  } catch { /* Lease expiry recovers a suspended worker or lost backend response. */ }
  finally { running = false; }
}
