export {};
// Runs at document_start in MAIN only on our owned detail page. Observe the
// normal page's responses; never obtain tokens, issue private API calls or guess relations.
(() => {
  if (!new URL(location.href).searchParams.has('crr_context')) return;
  const state: Record<string, unknown> = {};
  (window as unknown as { __crrContext: unknown }).__crrContext = state;
  const accept = (value: unknown): void => {
    let remaining = 15000;
    const walk = (item: unknown): void => {
      if (--remaining < 0 || !item || typeof item !== 'object') return;
      const obj = item as Record<string, any>;
      const legacy = obj.legacy;
      const user = obj.core?.user_results?.result;
      const author = user?.legacy?.screen_name ?? user?.core?.screen_name;
      const id = obj.rest_id;
      if (legacy && /^\d+$/.test(id) && typeof author === 'string' && legacy.conversation_id_str) {
        const text = obj.note_tweet?.note_tweet_results?.result?.text ?? legacy.full_text;
        const date = new Date(legacy.created_at);
        if (typeof text === 'string' && text.trim() && text.length <= 12000 && Number.isFinite(date.getTime())) {
          state[id] = { tweet_id: id, author, text, posted_at: date.toISOString(),
            parent_id: legacy.in_reply_to_status_id_str ?? null, relation_source: 'x_replied_to_field',
            language: legacy.lang ?? 'unknown',
            completeness: legacy.truncated ? 'partial' : legacy.extended_entities?.media?.length ? 'media_incomplete' : 'complete' };
        }
      }
      for (const child of Object.values(obj)) {
        if (Array.isArray(child)) child.forEach(walk);
        else if (child && typeof child === 'object') walk(child);
      }
    };
    walk(value);
  };
  const parse = (text: string): void => {
    if (text.length > 2500000) return;
    try { accept(JSON.parse(text)); } catch { /* Not tweet data. */ }
  };
  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    if (response.url.includes('/graphql/') && (response.status===429 || response.status>=500)) {
      (window as unknown as { __crrContextError: string }).__crrContextError='NETWORK_OR_RATE_LIMIT';
    }
    if (response.ok && response.url.includes('/graphql/') && /TweetDetail|TweetResultByRestId/.test(response.url)) {
      void response.clone().text().then(parse).catch(() => undefined);
    }
    return response;
  };
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', () => {
      if (!/\/graphql\/.*(?:TweetDetail|TweetResultByRestId)/.test(this.responseURL)) return;
      if (this.status===429 || this.status>=500) {
        (window as unknown as { __crrContextError: string }).__crrContextError='NETWORK_OR_RATE_LIMIT';
      }
      try {
        if (this.responseType === 'json') accept(this.response);
        else if (!this.responseType || this.responseType === 'text') parse(this.responseText);
      } catch { /* Page request failed. */ }
    }, { once: true });
    return originalSend.apply(this, args);
  };
})();
