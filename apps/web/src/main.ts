import "./style.css";
import { loadV2Dashboard, type HealthResponse, type PostsResponse, type RadarResponse, type TiboPost } from "./api";
import { actionCopy, compactBasis, escapeHtml, formatTime, tone } from "./radar-ui";

declare const __APP_VERSION__: string;
type DashboardData = { radar: RadarResponse; health: HealthResponse; posts: PostsResponse };

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app is required");
const app: HTMLElement = root;
let lastSuccessful: { data: DashboardData; receivedAt: Date } | null = null;
let refreshing = false;

function statusBadge(level: RadarResponse["action_level"]): string {
  return `<span class="level level-${tone(level)}"><i aria-hidden="true"></i>${escapeHtml(level)}</span>`;
}

function stateLabel(state: string): string {
  return ({ ready: "判断已就绪", processing: "正在分析 / 判断", failed: "模型请求失败", stale: "判断已过期", blocked: "模型未配置" } as Record<string, string>)[state] ?? state;
}

function estimateWindow(radar: RadarResponse): string {
  if (!radar.estimated_start && !radar.estimated_end) return "当前信号暂不能确定";
  if (radar.estimated_start && radar.estimated_end) return `${formatTime(radar.estimated_start)} — ${formatTime(radar.estimated_end)}`;
  return formatTime(radar.estimated_start ?? radar.estimated_end);
}

function evidenceLinks(ids: string[]): string {
  if (!ids.length) return `<span class="empty-inline">本轮未引用具体记录</span>`;
  return ids.map((id) => `<a class="evidence-link" href="https://x.com/thsottiaux/status/${encodeURIComponent(id)}" target="_blank" rel="noreferrer">${escapeHtml(id)}</a>`).join("");
}

function postRow(post: TiboPost): string {
  const original = post.original_text || post.text || "（正文为空）";
  const translated = post.translated_text || (post.original_language === "zh" ? original : "翻译暂不可用");
  const showOriginal = Boolean(post.translated_text && post.translated_text.trim() !== original.trim());
  const analysisState = post.analysis
    ? `${post.analysis.category ?? "other"} · ${post.analysis.summary ?? "已分析"}`
    : post.analysis_status === "FAILED" ? `分析失败：${post.processing_error ?? "未知错误"}` : "等待分析";
  return `<article class="post-row">
    <div><span class="mono">${escapeHtml(formatTime(post.posted_at))}</span><span class="source">${escapeHtml(post.is_reply ? "REPLY" : "POST")}</span></div>
    <div class="post-copy"><p class="translation">${escapeHtml(translated)}</p>${showOriginal ? `<details><summary>英文原文</summary><p lang="en">${escapeHtml(original)}</p></details>` : ""}<small>${escapeHtml(analysisState)}</small></div>
    <a href="${escapeHtml(post.url)}" target="_blank" rel="noreferrer" aria-label="在 X 查看推文 ${escapeHtml(post.tweet_id)}">在 X 查看 ↗</a>
  </article>`;
}

function specialResets(radar: RadarResponse): string {
  if (!radar.special_resets.length) return `<div class="empty purple-empty">当前没有经过验证的 Special Reset。</div>`;
  return radar.special_resets.map((event) => `<article class="special-card">
    <span>${escapeHtml(event.special_type ?? "OTHER")} · PURPLE</span><strong>${escapeHtml(event.title)}</strong>
    <p>${escapeHtml(event.summary)}</p><small>${escapeHtml(event.scope ?? "unknown")} · ${escapeHtml(event.execution_stage ?? "unknown")} · ${escapeHtml(event.time_basis ?? "unknown")}</small>
    <time>${escapeHtml(formatTime(event.occurred_at))}</time>
  </article>`).join("");
}

function collectors(health: HealthResponse): string {
  const entries = Object.entries(health.collector || {});
  if (!entries.length) return `<div class="empty">Backend 重启后尚未收到 Collector 状态。</div>`;
  return entries.map(([name, state]) => `<div class="health-row"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(state.state)}</span><time>${escapeHtml(formatTime(state.last_seen_at))}</time></div>`).join("");
}

function refreshWarning(message: string, receivedAt: Date): string {
  return `<div class="refresh-warning" role="status"><strong>刷新失败，正在显示最后一次成功数据</strong><span>${escapeHtml(message)} · 最后成功 ${escapeHtml(formatTime(receivedAt.toISOString()))}</span><button type="button" id="retry">重新连接</button></div>`;
}

function renderHome(radar: RadarResponse, health: HealthResponse, posts: TiboPost[], warning = ""): string {
  const nextReset = radar.next_reset.estimated_at ? formatTime(radar.next_reset.estimated_at) : "等待可信历史";
  const nextResetState = radar.next_reset.status === "expired" ? "参考时间已过，尚无新的确认" : radar.next_reset.basis;
  const lastReset = radar.last_full_reset
    ? `${formatTime(radar.last_full_reset.occurred_at)} · ${radar.last_full_reset.title}`
    : "最近一次完整 Reset 尚无足够证据确认";
  const horizons = [["24H", radar.horizon_24h], ["48H", radar.horizon_48h], ["72H", radar.horizon_72h]] as const;
  const judgeState = stateLabel(radar.judgement_state);
  const pending = health.intelligence?.pending_jobs ?? 0;

  return `<main>${warning}
    <section class="action-grid">
      <article class="action-card level-${tone(radar.action_level)}"><span class="eyebrow">ACTION LEVEL</span>${statusBadge(radar.action_level)}
        <h1>${escapeHtml(actionCopy(radar.action_level))}</h1><p>关注的问题：下一次 Codex Reset 是否正在临近？</p>
        <span class="state-pill">${escapeHtml(judgeState)}</span>
      </article>
      <article class="next-card"><span class="eyebrow">DEFAULT REFERENCE</span><strong>${escapeHtml(nextReset)}</strong><p>${escapeHtml(nextResetState)}</p>
        <hr><span class="eyebrow">CURRENT SIGNAL WINDOW</span><strong>${escapeHtml(estimateWindow(radar))}</strong><p>${escapeHtml(compactBasis(radar.estimate_basis))}</p>
        <details class="estimate-details"><summary>查看完整时间依据</summary><p>${escapeHtml(radar.estimate_basis)}</p></details></article>
    </section>
    <section class="horizon-grid" aria-label="Reset horizons">${horizons.map(([label, level]) => `<article class="horizon level-${tone(level)}"><span>${label}</span>${statusBadge(level)}<p>${escapeHtml(actionCopy(level))}</p></article>`).join("")}</section>
    <section class="content-grid">
      <article class="panel why-panel"><header><span class="eyebrow">WHY</span><h2>DeepSeek 判断依据</h2></header><p class="reason">${escapeHtml(radar.reason_summary)}</p>
        <div class="evidence-list" aria-label="判断证据">${evidenceLinks(radar.evidence_post_ids)}</div>
        <dl><div><dt>Data Health</dt><dd>${escapeHtml(radar.data_health)}</dd></div><div><dt>Judge</dt><dd>${escapeHtml(radar.judgement_id ? `#${radar.judgement_id}` : judgeState)}</dd></div><div><dt>判断时间</dt><dd>${escapeHtml(formatTime(radar.judged_at))}</dd></div><div><dt>有效至</dt><dd>${escapeHtml(formatTime(radar.valid_until))}</dd></div></dl>
      </article>
      <article class="panel reset-panel"><header><span class="eyebrow">LAST FULL RESET</span><h2>当前周期起点</h2></header><p class="reason">${escapeHtml(lastReset)}</p>
        ${radar.last_full_reset ? `<p class="event-meta">${escapeHtml(radar.last_full_reset.scope ?? "unknown")} · ${escapeHtml(radar.last_full_reset.execution_stage ?? "unknown")} · ${escapeHtml(radar.last_full_reset.time_basis ?? "unknown")}</p>` : ""}
        <small>只有经过语义核验的 FULL_RESET 会开启新周期；特殊额度事件不改变这里。</small></article>
    </section>
    <section class="panel"><header><span class="eyebrow purple-text">SPECIAL RESET · PURPLE</span><h2>特殊额度事件</h2></header><div class="special-grid">${specialResets(radar)}</div></section>
    <section class="content-grid lower-grid">
      <article class="panel"><header><span class="eyebrow">RECENT TIBO POSTS</span><h2>最近公开内容与中文翻译</h2></header><div class="post-list">${posts.length ? posts.map(postRow).join("") : `<div class="empty">V2 数据库暂无内容。</div>`}</div></article>
      <article class="panel"><header><span class="eyebrow">DATA HEALTH</span><h2>本地运行状态</h2></header>
        <div class="health-summary"><strong>${escapeHtml(health.status.toUpperCase())}</strong><span>DB ${escapeHtml(health.database.status)} · ${escapeHtml(String(health.database.counts.tibo_posts ?? 0))} posts</span></div>
        <p class="pipeline-summary">Intelligence：${escapeHtml(String((health.intelligence?.pipeline.status as string | undefined) ?? "unknown"))} · 待处理 ${escapeHtml(String(pending))}</p><div class="collector-list">${collectors(health)}</div>
      </article>
    </section>
  </main>`;
}

function renderOps(health: HealthResponse, warning = ""): string {
  return `<main class="ops-page">${warning}<section class="panel"><span class="eyebrow">OPS</span><h1>本地运行诊断</h1><pre>${escapeHtml(JSON.stringify({ status: health.status, version: health.version, commit: health.commit, database: health.database, intelligence: health.intelligence, runtime: health.runtime }, null, 2))}</pre></section></main>`;
}

function shell(content: string, backendVersion: string): string {
  return `<div class="shell"><header class="topbar"><a class="brand" href="#/">CRR <span>${escapeHtml(__APP_VERSION__)}</span></a><nav aria-label="主导航"><a href="#/">Radar</a><a href="#/ops">Ops</a></nav></header>${content}<footer><span>Codex Reset Radar ${escapeHtml(__APP_VERSION__)}</span><span>Backend ${escapeHtml(backendVersion)}</span><span>Local intelligence runtime</span></footer></div>`;
}

function render(data: DashboardData, warning = ""): void {
  const content = location.hash === "#/ops" ? renderOps(data.health, warning) : renderHome(data.radar, data.health, data.posts.items, warning);
  app.innerHTML = shell(content, data.health.version);
  document.querySelector<HTMLButtonElement>("#retry")?.addEventListener("click", () => void refresh());
}

async function refresh(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  if (!lastSuccessful) app.innerHTML = `<div class="loading-shell" role="status">正在读取本地 Backend API…</div>`;
  try {
    const data = await loadV2Dashboard();
    lastSuccessful = { data, receivedAt: new Date() };
    render(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (lastSuccessful) render(lastSuccessful.data, refreshWarning(message, lastSuccessful.receivedAt));
    else app.innerHTML = shell(`<main><section class="panel error-panel"><span class="eyebrow">BACKEND UNAVAILABLE</span><h1>本地 V2 Backend 暂不可用</h1><p>${escapeHtml(message)}</p><button type="button" id="retry">重新连接</button></section></main>`, "unavailable");
    document.querySelector<HTMLButtonElement>("#retry")?.addEventListener("click", () => void refresh());
  } finally {
    refreshing = false;
  }
}

window.addEventListener("hashchange", () => lastSuccessful ? render(lastSuccessful.data) : void refresh());
void refresh();
window.setInterval(() => void refresh(), 60_000);
