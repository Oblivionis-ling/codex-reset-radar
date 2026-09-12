import "./style.css";
import { loadV2Dashboard, type HealthResponse, type RadarResponse, type TiboPost } from "./api";
import { actionCopy, escapeHtml, formatTime, tone } from "./radar-ui";

declare const __APP_VERSION__: string;

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app is required");
const app: HTMLElement = root;

function statusBadge(level: RadarResponse["action_level"]): string {
  return `<span class="level level-${tone(level)}"><i aria-hidden="true"></i>${escapeHtml(level)}</span>`;
}

function postRow(post: TiboPost): string {
  return `<article class="post-row">
    <div><span class="mono">${escapeHtml(formatTime(post.posted_at))}</span><span class="source">${escapeHtml(post.is_reply ? "REPLY" : "POST")}</span></div>
    <p>${escapeHtml(post.text || "（正文为空）")}</p>
    <a href="${escapeHtml(post.url)}" target="_blank" rel="noreferrer">在 X 查看 ↗</a>
  </article>`;
}

function specialResets(radar: RadarResponse): string {
  if (!radar.special_resets.length) {
    return `<div class="empty purple-empty">当前没有经过验证的 Special Reset。</div>`;
  }
  return radar.special_resets.map((event) => `<article class="special-card">
    <span>${escapeHtml(event.special_type ?? "OTHER")}</span>
    <strong>${escapeHtml(event.title)}</strong>
    <p>${escapeHtml(event.summary)}</p>
    <time>${escapeHtml(formatTime(event.occurred_at))}</time>
  </article>`).join("");
}

function collectors(health: HealthResponse): string {
  const entries = Object.entries(health.collector || {});
  if (!entries.length) return `<div class="empty">Collector 尚未发送本次运行的状态。</div>`;
  return entries.map(([name, state]) => `<div class="health-row">
    <strong>${escapeHtml(name)}</strong><span>${escapeHtml(state.state)}</span><time>${escapeHtml(formatTime(state.last_seen_at))}</time>
  </div>`).join("");
}

function renderHome(radar: RadarResponse, health: HealthResponse, posts: TiboPost[]): string {
  const nextReset = radar.next_reset.estimated_at
    ? formatTime(radar.next_reset.estimated_at)
    : "waiting for verified history";
  const lastReset = radar.last_full_reset
    ? `${formatTime(radar.last_full_reset.occurred_at)} · ${radar.last_full_reset.title}`
    : "尚无 canonical FULL_RESET";
  const horizons = [
    ["24H", radar.horizon_24h],
    ["48H", radar.horizon_48h],
    ["72H", radar.horizon_72h]
  ] as const;

  return `<main>
    <section class="action-grid">
      <article class="action-card level-${tone(radar.action_level)}">
        <span class="eyebrow">ACTION LEVEL</span>
        ${statusBadge(radar.action_level)}
        <h1>${escapeHtml(actionCopy(radar.action_level))}</h1>
        <p>关注的问题：下一次 Codex Reset 是否正在临近？</p>
      </article>
      <article class="next-card">
        <span class="eyebrow">NEXT RESET</span>
        <strong>${escapeHtml(nextReset)}</strong>
        <p>${escapeHtml(radar.next_reset.basis)}</p>
      </article>
    </section>
    <section class="horizon-grid" aria-label="Reset horizons">
      ${horizons.map(([label, level]) => `<article class="horizon level-${tone(level)}"><span>${label}</span>${statusBadge(level)}<p>${escapeHtml(actionCopy(level))}</p></article>`).join("")}
    </section>

    <section class="content-grid">
      <article class="panel why-panel">
        <header><span class="eyebrow">WHY</span><h2>判断依据</h2></header>
        <p class="reason">${escapeHtml(radar.reason_summary)}</p>
        <dl><div><dt>Data Health</dt><dd>${escapeHtml(radar.data_health)}</dd></div><div><dt>Judge Time</dt><dd>${escapeHtml(formatTime(radar.judged_at))}</dd></div></dl>
      </article>
      <article class="panel reset-panel">
        <header><span class="eyebrow">LAST FULL RESET</span><h2>当前周期起点</h2></header>
        <p class="reason">${escapeHtml(lastReset)}</p>
        <small>只有 FULL_RESET 会开启新的 Reset Cycle；Special Reset 不改变这里。</small>
      </article>
    </section>

    <section class="panel">
      <header><span class="eyebrow purple-text">SPECIAL RESET · PURPLE</span><h2>特殊额度事件</h2></header>
      <div class="special-grid">${specialResets(radar)}</div>
    </section>

    <section class="content-grid lower-grid">
      <article class="panel">
        <header><span class="eyebrow">RECENT TIBO POSTS</span><h2>最近公开内容</h2></header>
        <div class="post-list">${posts.length ? posts.map(postRow).join("") : `<div class="empty">V2 数据库尚无已迁移或新采集内容。</div>`}</div>
      </article>
      <article class="panel">
        <header><span class="eyebrow">DATA HEALTH</span><h2>本地运行状态</h2></header>
        <div class="health-summary"><strong>${escapeHtml(health.status.toUpperCase())}</strong><span>DB ${escapeHtml(health.database.status)} · ${escapeHtml(String(health.database.counts.tibo_posts ?? 0))} posts</span></div>
        <div class="collector-list">${collectors(health)}</div>
      </article>
    </section>
  </main>`;
}

function renderOps(health: HealthResponse): string {
  return `<main class="ops-page"><section class="panel"><span class="eyebrow">OPS FOUNDATION</span><h1>运行诊断预留页</h1><p>Alpha 1 只保留最小状态，不把运维噪声放进主 Radar。</p><pre>${escapeHtml(JSON.stringify({ status: health.status, version: health.version, commit: health.commit, database: health.database, runtime: health.runtime }, null, 2))}</pre></section></main>`;
}

function shell(content: string, backendVersion: string): string {
  return `<div class="shell">
    <header class="topbar"><a class="brand" href="#/">CRR <span>V2 Alpha 1</span></a><nav><a href="#/">Radar</a><a href="#/ops">Ops</a></nav></header>
    ${content}
    <footer><span>Codex Reset Radar ${escapeHtml(__APP_VERSION__)}</span><span>Backend ${escapeHtml(backendVersion)}</span><span>Local full-stack runtime</span></footer>
  </div>`;
}

async function refresh(): Promise<void> {
  app.innerHTML = `<div class="loading-shell">正在读取本地 Backend API…</div>`;
  try {
    const data = await loadV2Dashboard();
    const content = location.hash === "#/ops" ? renderOps(data.health) : renderHome(data.radar, data.health, data.posts.items);
    app.innerHTML = shell(content, data.health.version);
  } catch (error) {
    app.innerHTML = shell(`<main><section class="panel error-panel"><span class="eyebrow">BACKEND UNAVAILABLE</span><h1>本地 V2 Backend 暂不可用</h1><p>${escapeHtml(error instanceof Error ? error.message : error)}</p><button type="button" id="retry">重新连接</button></section></main>`, "unavailable");
    document.querySelector<HTMLButtonElement>("#retry")?.addEventListener("click", () => void refresh());
  }
}

window.addEventListener("hashchange", () => void refresh());
void refresh();
window.setInterval(() => void refresh(), 60_000);
