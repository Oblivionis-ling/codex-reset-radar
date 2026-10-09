import "./style.css";
import {
  loadPredictionHistory,
  loadV2Dashboard,
  PREDICTION_TARGETS,
  type HealthResponse,
  type PredictionHistoryResponse,
  type PredictionLine,
  type PredictionTarget,
  type PostsResponse,
  type RadarResponse,
  type TiboPost
} from "./api";
import {
  actionCopy,
  anchorLimitationLabel,
  compactBasis,
  downgradePredictionOnRefreshFailure,
  escapeHtml,
  formatTime,
  historyMilestones,
  historyRevisionLabel,
  outputAvailabilityLabel,
  predictionHealthLabel,
  predictionIsNotCurrent,
  predictionMethodLabel,
  predictionReasonLabel,
  predictionStateLabel,
  predictionStatusProjectionNotes,
  predictionTimeSummary,
  tone
} from "./radar-ui";

declare const __APP_VERSION__: string;
type DashboardData = { radar: RadarResponse; health: HealthResponse; posts: PostsResponse };

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app is required");
const app: HTMLElement = root;
let lastSuccessful: { data: DashboardData; receivedAt: Date } | null = null;
let refreshing = false;
let routeRevision = 0;
let lastRefreshFailure: string | null = null;

function statusBadge(level: RadarResponse["action_level"]): string {
  return `<span class="level level-${tone(level)}"><i aria-hidden="true"></i>${escapeHtml(level)}</span>`;
}

function stateLabel(state: string): string {
  return ({ ready: "判断已就绪", processing: "正在分析 / 判断", failed: "模型请求失败", stale: "判断已过期", data_stale: "数据过期 · 暂不能可靠判断", invalid: "已有结果 · 校验未通过", insufficient_input: "可用资料不足", blocked: "模型未配置" } as Record<string, string>)[state] ?? state;
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
    <div class="post-copy"><p class="translation">${escapeHtml(translated)}</p>${showOriginal ? `<details><summary>原文</summary><p>${escapeHtml(original)}</p></details>` : ""}<small>${escapeHtml(analysisState)}</small>${replyContext(post)}</div>
    <a href="${escapeHtml(post.url)}" target="_blank" rel="noreferrer" aria-label="在 X 查看推文 ${escapeHtml(post.tweet_id)}">在 X 查看 ↗</a>
  </article>`;
}

function replyContext(post: TiboPost): string {
  const context = post.reply_context;
  if (!post.is_reply || !context) return '';
  const labels: Record<string,string> = { READY:'父帖已取得', PARTIAL:'上下文部分可用', UNAVAILABLE:'父帖尚不可用',
    RELATION_UNCONFIRMED:'直接回复关系待确认', BODY_UNAVAILABLE:'父帖正文待获取', CONTENT_RESTRICTED:'内容使用受限',
    INCOMPLETE_CONTENT:'媒体或正文上下文不完整', DEPTH_LIMIT:'已到最大追溯深度',
    LOGIN_REQUIRED:'需要重新登录 X', PAGE_LOADING:'详情页未完成加载', BROWSER_DISCONNECTED:'等待浏览器连接',
    USER_NAVIGATED:'辅助页已被手动关闭或导航', NETWORK_OR_RATE_LIMIT:'网络错误或限流', ANCESTOR_RELATION_UNCONFIRMED:'更上层关系尚未确认' };
  return `<details><summary>回复上下文 · ${escapeHtml(labels[context.state] ?? context.state)}</summary>
    <p>${escapeHtml(context.missing.map(value=>labels[value]??value).join('；'))}</p>
    <small>${escapeHtml(post.context_acquisition?.status ?? '')} · ${escapeHtml(labels[post.context_acquisition?.reason ?? ''] ?? post.context_acquisition?.reason ?? '')}</small>
    ${context.nodes.map(node=>`<blockquote><small>${node.depth===1?'直接父帖':'上层上下文'} · @${escapeHtml(node.author)} · ${escapeHtml(formatTime(node.posted_at))}</small><p>${escapeHtml(node.text)}</p><a href="https://x.com/i/status/${encodeURIComponent(node.tweet_id)}" target="_blank" rel="noreferrer">查看父帖</a></blockquote>`).join('')}
    <small>补全后分析时间：${escapeHtml(formatTime(post.analysis?._analysed_at ?? null))}</small></details>`;
}

function specialResets(radar: RadarResponse): string {
  if (!radar.special_resets.length) return `<div class="empty purple-empty">当前没有经过验证的 Special Reset。</div>`;
  return radar.special_resets.map((event) => `<article class="special-card">
    <span>${escapeHtml(event.special_type ?? "OTHER")} · PURPLE</span><strong>${escapeHtml(event.title)}</strong>
    <p>${escapeHtml(event.summary)}</p><small>${escapeHtml(event.scope ?? "unknown")} · ${escapeHtml(event.execution_stage ?? "unknown")} · ${escapeHtml(event.time_basis ?? "unknown")}</small>
    <time>${escapeHtml(formatTime(event.occurred_at))}</time>
  </article>`).join("");
}

function specialAnnouncements(radar: RadarResponse): string {
  return radar.special_announcements.map(a=>`<article class="special-card">
    <span>重置卡相关预告 · 待核验</span><strong>尚未确认发放</strong>
    ${radar.current_data_health!=='HEALTHY'?'<small>采集过期 · 最后已知信息</small>':''}
    <p>${escapeHtml(a.summary)}</p><small>范围：${escapeHtml(a.scope)} · ${a.scheduled_at?escapeHtml(formatTime(a.scheduled_at)):'日程未确认'}</small>
    <time>发帖 ${escapeHtml(formatTime(a.posted_at))}</time>
    <a href="https://x.com/thsottiaux/status/${encodeURIComponent(a.tweet_id)}" target="_blank" rel="noreferrer">查看预告原帖</a>
  </article>`).join('');
}

const predictionTitles: Record<PredictionTarget, string> = {
  NORMAL_WEEKLY: "正常周额度参考（Normal）",
  EXTRA_FULL: "额外完整重置预测（Extra Full）",
  BANKED: "重置卡发放预测（Banked）"
};

function predictionFormLabel(form: string): string {
  const labels: Record<string, string> = {
    point: "点值",
    range: "范围",
    date: "日期粒度",
    proxy: "旧记录发帖时间代理",
    start_only: "仅起点",
    end_only: "仅终点",
    lower_bound: "仅起点",
    upper_bound: "仅终点",
    relative: "相对表达式",
    unknown: "未知形式"
  };
  return labels[form.toLowerCase()] ?? form;
}

function updatedAtSourceLabel(source: string | null): string {
  if (source === "judgement_time") return "（判定时间）";
  if (source === "ledger_recorded_at") return "（账本记录时间）";
  if (source === "output_available_at_observation") return "（输出可用观察时间）";
  return "";
}

function anchorTimeBasisLabel(value: string): string {
  if (value === "post_time_proxy") return "发帖时间代理（不是实际执行开始）";
  if (value === "legacy_anchor_precision_unknown") return "旧锚点精度未核实";
  return value;
}

function predictionHistoryHref(target: PredictionTarget, seriesId: string): string {
  const query = new URLSearchParams({ target, series_id: seriesId });
  return `#/predictions/history?${query.toString()}`;
}

function predictionLineCard(
  line: PredictionLine,
  historyAvailable: boolean,
  globalHealth: NonNullable<RadarResponse["prediction"]>["health"]
): string {
  const notCurrent = predictionIsNotCurrent(line)
    || globalHealth.current_data_health !== "HEALTHY"
    || globalHealth.refresh_failed
    || (line.target !== "NORMAL_WEEKLY" && (
      !globalHealth.validation_valid
      || globalHealth.generation_data_health !== "HEALTHY"
      || !globalHealth.judgement_usable
    ));
  const state = notCurrent && ["ready", "current", "available"].includes(line.state.toLowerCase())
    ? "stale" : line.state;
  const validity = line.valid_until
    ? `${predictionStateLabel(line.validity_state)} · 有效至 ${formatTime(line.valid_until)}`
    : predictionStateLabel(line.validity_state);
  const health = line.health_reason
    ? `${predictionHealthLabel(line.health_state)} · ${line.health_reason}`
    : predictionHealthLabel(line.health_state);
  const outputAvailability = outputAvailabilityLabel(line.output_available_at);
  const statusProjection = predictionStatusProjectionNotes(line);
  const statusProjectionNote = statusProjection.length
    ? `<p class="prediction-status-projection" role="status">${escapeHtml(statusProjection.join(" · "))}</p>`
    : "";
  const basis = line.basis && line.basis !== "user_full_plus_7d"
    ? `<div><dt>依据</dt><dd>${escapeHtml(line.basis)}</dd></div>`
    : "";
  const historyLink = historyAvailable && line.series_id
    ? `<a class="prediction-history-link" href="${escapeHtml(predictionHistoryHref(line.target, line.series_id))}">查看此系列历史</a>`
    : `<span class="empty-inline">此系列暂无历史入口</span>`;
  const relativeDetails = line.relative_expression || line.expression || line.relative_anchor || line.unresolved_reason || line.anchor_limitation || line.anchor_time_basis
    ? `<details class="prediction-relative-details"><summary>时间表达、锚点与解析限制</summary>
      ${line.relative_expression || line.expression ? `<p>原始表达：${escapeHtml(line.relative_expression ?? line.expression)}</p>` : ""}
      ${line.relative_anchor ? `<p>发帖时间锚点：${escapeHtml(line.relative_anchor)}</p>` : ""}
      ${line.anchor_time_basis ? `<p>锚点时间依据：${escapeHtml(anchorTimeBasisLabel(line.anchor_time_basis))}</p>` : ""}
      ${line.anchor_limitation ? `<p>锚点限制：${escapeHtml(anchorLimitationLabel(line.anchor_limitation))}</p>` : ""}
      ${line.unresolved_reason ? `<p>未解析原因：${escapeHtml(line.unresolved_reason)}</p>` : ""}</details>`
    : "";
  const anchorCaveat = line.anchor_limitation
    ? `<p class="prediction-note">锚点限制：${escapeHtml(anchorLimitationLabel(line.anchor_limitation))}</p>`
    : line.form.toLowerCase() === "proxy"
      ? `<p class="prediction-note">旧记录仅为发帖时间代理，实际执行开始未核实。</p>`
      : "";
  const eligibilityWarning = notCurrent
    ? `<p class="prediction-stale-warning" role="status">${escapeHtml(globalHealth.refresh_failed
      ? "刷新失败；下方仅为最后成功数据，不作为当前建议。"
      : line.status_projection
        ? line.eligibility_reason
          ? `${predictionReasonLabel(line.eligibility_reason)}；不作为当前建议。`
          : "当前不可用，不作为当前建议；请查看运行状态、有效性与数据健康信息。"
        : predictionReasonLabel(line.eligibility_reason ?? "此记录未通过当前全局校验/健康门控，不作为当前建议。"))}</p>`
    : "";
  return `<article class="prediction-line${line.target === "BANKED" ? " prediction-line-banked" : ""}${notCurrent ? " prediction-line-stale" : ""}">
    <header><span class="eyebrow${line.target === "BANKED" ? " purple-text" : ""}">${line.target === "BANKED" ? "BANKED · PURPLE" : escapeHtml(line.target)}</span>
      <h3>${escapeHtml(predictionTitles[line.target])}</h3><span class="prediction-state">${escapeHtml(predictionStateLabel(state))}</span></header>
    ${line.target === "NORMAL_WEEKLY" ? `<p class="prediction-note">参考规则，非官方恢复承诺。</p>${anchorCaveat}` : anchorCaveat}
    <strong class="prediction-time">${escapeHtml(predictionTimeSummary(line))}</strong>
    ${statusProjectionNote}
    <dl>
      <div><dt>时间形式</dt><dd>${escapeHtml(predictionFormLabel(line.form))}</dd></div>
      <div><dt>来源 / 方法</dt><dd>${escapeHtml(predictionMethodLabel(line.method, line.basis))}</dd></div>
      <div><dt>时区 / 精度</dt><dd>${escapeHtml(line.source_timezone ?? "未确认时区")} · ${escapeHtml(line.precision ?? "未提供精度")}</dd></div>
      <div><dt>目标范围</dt><dd>${escapeHtml(line.scope ?? "范围未记录")}</dd></div>
      <div><dt>时间依据</dt><dd>${escapeHtml(line.time_basis ?? "未说明")}${line.date_boundaries ? ` · ${escapeHtml(line.date_boundaries)}` : ""}</dd></div>
      <div><dt>更新时间</dt><dd>${escapeHtml(line.updated_at ? formatTime(line.updated_at) : "未记录")}${escapeHtml(updatedAtSourceLabel(line.updated_at_source))}</dd></div>
      <div><dt>输出可用时间</dt><dd>${escapeHtml(outputAvailability)}${line.output_availability_kind ? ` · 来源 ${escapeHtml(line.output_availability_kind)}` : ""}</dd></div>
      <div><dt>有效性</dt><dd>${escapeHtml(validity)}</dd></div>
      <div><dt>数据健康</dt><dd>${escapeHtml(health)}</dd></div>${basis}
    </dl>
    ${line.status_projection ? "" : `<p class="prediction-reason">${escapeHtml(line.reason ? predictionReasonLabel(line.reason) : line.health_reason ?? "暂无可审查依据")}</p>`}
    ${relativeDetails}${eligibilityWarning}
    ${historyLink}
  </article>`;
}

function predictionLines(radar: RadarResponse): string {
  const prediction = radar.prediction;
  if (!prediction) {
    return `<section class="panel prediction-panel" aria-labelledby="prediction-heading">
      <header><span class="eyebrow">PREDICTION LINES</span><h2 id="prediction-heading">三条时间线</h2></header>
      <p class="empty">当前 Backend 未提供三线预测扩展；上方旧参考和 Full 时间字段仍保持原语义。</p>
    </section>`;
  }
  const cards = PREDICTION_TARGETS.map((target) => predictionLineCard(
    prediction.lines[target],
    prediction.capabilities.history,
    prediction.health
  )).join("");
  const collectorHealth = Object.entries(prediction.health.current_collector_health)
    .map(([name, value]) => {
      const item = value && typeof value === "object" ? value as Record<string, unknown> : {};
      return `${name}：${predictionHealthLabel(typeof item.state === "string" ? item.state : null)}${typeof item.reason === "string" ? `（${predictionReasonLabel(item.reason)}）` : ""}`;
    }).join("；");
  const globalStatus = prediction.health.refresh_failed
    ? `刷新失败：${prediction.health.refresh_failure_reason ?? "仅显示最后成功数据"}`
    : `预测投影：${predictionStateLabel(prediction.state)}`;
  return `<section class="panel prediction-panel" aria-labelledby="prediction-heading">
    <header><span class="eyebrow">PREDICTION LINES · ${escapeHtml(prediction.version)}</span><h2 id="prediction-heading">三条时间线</h2></header>
    <p class="prediction-global-health" role="status">${escapeHtml(globalStatus)} · 全局校验：${escapeHtml(predictionReasonLabel(prediction.health.validation_reason))} · 本轮生成健康：${escapeHtml(predictionHealthLabel(prediction.health.generation_data_health))}${prediction.health.generation_health_reason ? `（${escapeHtml(predictionReasonLabel(prediction.health.generation_health_reason))}）` : ""} · 当前采集健康：${escapeHtml(predictionHealthLabel(prediction.health.current_data_health))}${collectorHealth ? ` · ${escapeHtml(collectorHealth)}` : ""}</p>
    <div class="prediction-grid">${cards}</div>
  </section>`;
}

type PageRoute =
  | { page: "home" }
  | { page: "ops" }
  | { page: "history"; target: PredictionTarget; seriesId: string; limit: number }
  | { page: "invalid-history" };

function pageRoute(): PageRoute {
  if (location.hash === "#/ops") return { page: "ops" };
  const prefix = "#/predictions/history";
  if (location.hash.startsWith(prefix)) {
    const rawQuery = location.hash.slice(prefix.length).replace(/^\?/, "");
    const params = new URLSearchParams(rawQuery);
    const target = params.get("target");
    const seriesId = params.get("series_id");
    if (PREDICTION_TARGETS.includes(target as PredictionTarget) && seriesId) {
      const requestedLimit = Number(params.get("limit") ?? 100);
      const limit = Number.isFinite(requestedLimit)
        ? Math.max(1, Math.min(200, Math.trunc(requestedLimit)))
        : 100;
      return { page: "history", target: target as PredictionTarget, seriesId, limit };
    }
    return { page: "invalid-history" };
  }
  return { page: "home" };
}

function historyVersion(line: PredictionLine, label: string): string {
  const revisions = historyRevisionLabel(line);
  const statusProjection = predictionStatusProjectionNotes(line);
  const statusProjectionNote = statusProjection.length
    ? `<p class="history-status-projection" role="status">${escapeHtml(statusProjection.join(" · "))}</p>`
    : "";
  const available = outputAvailabilityLabel(line.output_available_at);
  const provenance = line.is_synthetic === true ? "合成账本版本"
    : line.is_synthetic === false ? "非合成来源（不代表时间事实已核实）" : "来源属性未记录";
  const relativeDetails = line.relative_expression || line.expression || line.relative_anchor || line.unresolved_reason || line.anchor_limitation || line.anchor_time_basis
    ? `<details><summary>时间表达与锚点限制</summary>
      ${line.relative_expression || line.expression ? `<p>原始表达：${escapeHtml(line.relative_expression ?? line.expression)}</p>` : ""}
      ${line.relative_anchor ? `<p>发帖时间锚点：${escapeHtml(line.relative_anchor)}</p>` : ""}
      ${line.anchor_time_basis ? `<p>锚点时间依据：${escapeHtml(anchorTimeBasisLabel(line.anchor_time_basis))}</p>` : ""}
      ${line.anchor_limitation ? `<p>锚点限制：${escapeHtml(anchorLimitationLabel(line.anchor_limitation))}</p>` : ""}
      ${line.unresolved_reason ? `<p>未解析原因：${escapeHtml(line.unresolved_reason)}</p>` : ""}</details>`
    : "";
  return `<article class="history-version">
    <span class="eyebrow">${escapeHtml(label)}</span><h3>${escapeHtml(revisions)} · ${escapeHtml(predictionStateLabel(line.state))}</h3>
    <strong>${escapeHtml(predictionTimeSummary(line))}</strong>
    ${statusProjectionNote}
    <dl><div><dt>输出可用时间</dt><dd>${escapeHtml(available)}${line.output_availability_kind ? ` · 来源 ${escapeHtml(line.output_availability_kind)}` : ""}</dd></div>
      <div><dt>形式 / 方法</dt><dd>${escapeHtml(predictionFormLabel(line.form))} · ${escapeHtml(predictionMethodLabel(line.method, line.basis))}</dd></div>
      <div><dt>范围 / 时区 / 精度 / 时间依据</dt><dd>${escapeHtml(line.scope ?? "范围未记录")} · ${escapeHtml(line.source_timezone ?? "未确认时区")} · ${escapeHtml(line.precision ?? "未提供精度")} · ${escapeHtml(line.time_basis ?? "未说明")}${line.date_boundaries ? ` · ${escapeHtml(line.date_boundaries)}` : ""}</dd></div>
      <div><dt>更新时间</dt><dd>${escapeHtml(line.updated_at ? formatTime(line.updated_at) : "未记录")}${escapeHtml(updatedAtSourceLabel(line.updated_at_source))}</dd></div>
      <div><dt>有效性 / 健康</dt><dd>${escapeHtml(predictionStateLabel(line.validity_state))} · ${escapeHtml(predictionHealthLabel(line.health_state))}</dd></div>
      <div><dt>问题版本 / 目标输出 ID</dt><dd>${escapeHtml(line.question_version ?? line.forecast_version ?? "未记录")} · ${escapeHtml(line.target_output_id ?? "未记录")}</dd></div>
      <div><dt>账本记录 / 来源</dt><dd>${escapeHtml(line.record_id ?? "记录 ID 未提供")} · ${escapeHtml(line.ledger_seq === null ? "追加序列未提供" : `追加序列 ${line.ledger_seq}`)} · ${escapeHtml(provenance)}</dd></div>
      <div><dt>依据</dt><dd>${escapeHtml(line.reason ? predictionReasonLabel(line.reason) : "暂无可审查依据")}</dd></div>
      <div><dt>前一版本</dt><dd>${escapeHtml(line.previous_id ?? "无")}</dd></div></dl>${relativeDetails}
  </article>`;
}

function historyAttemptsSection(history: PredictionHistoryResponse): string {
  if (!history.attempts.length) return "";
  const rows = history.attempts.map((attempt) => {
    const time = attempt.attempted_at ?? attempt.started_at ?? attempt.finished_at;
    const reason = attempt.reason ?? (attempt.reason_code ? predictionReasonLabel(attempt.reason_code) : "未提供原因");
    const timing = time ? ` · ${formatTime(time)}` : " · 时间未记录";
    return `<li><strong>${escapeHtml(predictionStateLabel(attempt.state))}</strong>${escapeHtml(timing)}<span> · ${escapeHtml(reason)}</span>${attempt.output_status ? `<span> · 输出：${escapeHtml(attempt.output_status)}</span>` : ""}</li>`;
  }).join("");
  const countBasis = history.attempt_count_basis === "target_projection_not_http_count"
    ? " · 按目标投影计数，不代表 HTTP 请求次数"
    : "";
  return `<details class="history-more"><summary>目标尝试与失败原因（${history.attempts.length}${history.attempts_truncated ? "+，已截断" : ""}${countBasis}）</summary><ul>${rows}</ul></details>`;
}

function renderHistoryPage(history: PredictionHistoryResponse, target: PredictionTarget, seriesId: string, warning = ""): string {
  const attemptsSection = historyAttemptsSection(history);
  if (history.state.toLowerCase() === "not_implemented") {
    return `<main><section class="panel prediction-history-page" aria-labelledby="history-heading">
      ${warning}<a class="back-link" href="#/">返回 Radar</a><span class="eyebrow">PREDICTION HISTORY</span>
      <h1 id="history-heading">${escapeHtml(predictionTitles[target])}</h1><p class="empty" role="status">历史版本暂不可展示。${escapeHtml(history.reason ? predictionReasonLabel(history.reason) : "")}</p>${attemptsSection}
    </section></main>`;
  }
  const milestones = historyMilestones(history.items);
  const labels = history.items.length <= 1 ? ["本次返回首条 / 末条"]
    : history.items.length === 2 ? ["本次返回首条", "本次返回末条"]
      : ["本次返回首条", "本次返回中间条", "本次返回末条"];
  const cards = milestones.map((line, index) => historyVersion(line, labels[index] ?? "版本")).join("");
  const middleIndex = Math.floor((history.items.length - 1) / 2);
  const otherMiddle = history.items.length > 3
    ? history.items.slice(1, -1).filter((_, index) => index + 1 !== middleIndex)
    : [];
  const otherMiddleDetails = otherMiddle.length
    ? `<details class="history-more"><summary>查看其余 ${otherMiddle.length} 个中间版本</summary><div class="history-grid">${otherMiddle.map((line) => historyVersion(line, "本次返回的中间版本")).join("")}</div></details>`
    : "";
  const truncated = history.truncated || history.total_count > history.items.length;
  const totalDescription = history.total_count_known ? `共 ${history.total_count} 条` : "账本未报告系列总数";
  const truncationNote = truncated
    ? `<p class="history-truncation" role="status">本次结果已截断：这里只标记“本次返回”的首条与末条，不能据此称为该系列绝对首次版本。${escapeHtml(totalDescription)}，当前返回 ${history.items.length} 条。</p>`
    : "";
  const seriesBoundaries = truncated
    ? history.first_items.length && history.last_items.length
      ? `<section class="history-boundaries" aria-labelledby="history-boundaries-heading">
          <h2 id="history-boundaries-heading">全系列账本边界版本</h2>
          <p>${escapeHtml(history.order_basis === "append_sequence_not_proven_temporal_or_pre_event_order"
            ? "以下首条／末条由 Ledger 边界 DTO 提供，按追加顺序标识；不证明真实时间先后或预测的事前评分顺序。"
            : "以下首条／末条由 Ledger 边界 DTO 提供；仅按账本返回顺序标识，不代表预测的事前评分顺序。")}</p>
          <div class="history-grid">${history.first_items.map((line) => historyVersion(line, "账本全系列首条")).join("")}${history.last_items.map((line) => historyVersion(line, "账本全系列末条")).join("")}</div>
        </section>`
      : `<p class="history-truncation" role="status">账本确认结果已截断，但没有提供可安全展示的全系列首末 DTO；本次窗口首条不能替代真实首条。</p>`
    : "";
  const stateNotice = ["ready", "current"].includes(history.state.toLowerCase())
    ? ""
    : `<p class="history-state-note" role="status">历史状态：${escapeHtml(predictionStateLabel(history.state))}${history.reason ? ` · ${escapeHtml(predictionReasonLabel(history.reason))}` : ""}</p>`;
  const content = history.items.length
    ? `<p class="history-count">按 Ledger 返回顺序展示本次读取的首条、中间条和末条；本次读取 ${history.items.length} 条。</p>${truncationNote}${seriesBoundaries}<div class="history-grid">${cards}</div>${otherMiddleDetails}${attemptsSection}`
    : `<p class="empty" role="status">此系列本次没有可显示的预测版本。${escapeHtml(history.reason ? predictionReasonLabel(history.reason) : "")}</p>${truncationNote}${seriesBoundaries}${attemptsSection}`;
  return `<main><section class="panel prediction-history-page" aria-labelledby="history-heading">
    ${warning}
    <a class="back-link" href="#/">返回 Radar</a><span class="eyebrow">PREDICTION HISTORY · ${escapeHtml(target)}</span>
    <h1 id="history-heading">${escapeHtml(predictionTitles[target])}</h1>
    <p class="history-series">系列 ${escapeHtml(seriesId)} · ${escapeHtml(totalDescription)}，已返回 ${history.items.length} 条</p>${stateNotice}${content}
  </section></main>`;
}

function renderHistoryError(target: PredictionTarget, seriesId: string, message: string): string {
  return `<main><section class="panel prediction-history-page" aria-labelledby="history-heading">
    <a class="back-link" href="#/">返回 Radar</a><span class="eyebrow">PREDICTION HISTORY</span>
    <h1 id="history-heading">${escapeHtml(predictionTitles[target])}</h1>
    <p class="refresh-warning" role="status">历史读取失败：${escapeHtml(message)}</p>
    <p class="history-series">系列 ${escapeHtml(seriesId)}</p><button type="button" id="retry">重新读取</button>
  </section></main>`;
}

function collectors(health: HealthResponse): string {
  const entries = Object.entries(health.collector || {});
  if (!entries.length) return `<div class="empty">Backend 重启后尚未收到 Collector 状态。</div>`;
  return entries.map(([name, state]) => `<div class="health-row"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(state.state)} · ${escapeHtml(state.reason??'')}<small>最后自报：${escapeHtml(state.reported_state??state.state)}</small></span><time>${escapeHtml(formatTime(state.last_seen_at))}</time></div>`).join("");
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
    <p role="status">判断时数据：${escapeHtml(radar.judgement_data_health)} · 当前采集：${escapeHtml(radar.current_data_health)} · 校验：${escapeHtml(radar.validation.reason)} · 最近处理：${escapeHtml(String(radar.judge_runtime.status??''))}${radar.judge_runtime.last_error?` · ${escapeHtml(String(radar.judge_runtime.last_error))}`:''}</p>
    ${radar.display_mode==='last_known' && radar.last_known_result?`<details><summary>最后已知模型结果（不是当前行动建议）</summary><p>主等级 ${escapeHtml(String(radar.last_known_result.action_level))} · 24/48/72h：${escapeHtml(['horizon_24h','horizon_48h','horizon_72h'].map(k=>String(radar.last_known_result?.[k])).join(' / '))}</p><p>${escapeHtml(String(radar.last_known_result.reason_summary))}</p></details>`:''}
    <section class="action-grid">
      <article class="action-card level-${tone(radar.action_level)}"><span class="eyebrow">ACTION LEVEL</span>${statusBadge(radar.action_level)}
        <h1>${escapeHtml(actionCopy(radar.action_level))}</h1><p>关注的问题：下一次 Codex Reset 是否正在临近？</p>
        <span class="state-pill">${escapeHtml(judgeState)}</span>
      </article>
      <article class="next-card"><span class="eyebrow">DEFAULT REFERENCE</span><strong>${escapeHtml(nextReset)}</strong><p>${escapeHtml(nextResetState)}</p>
        <hr><span class="eyebrow">CURRENT SIGNAL WINDOW</span><strong>${escapeHtml(estimateWindow(radar))}</strong><p>${escapeHtml(compactBasis(radar.estimate_basis))}</p>
        <details class="estimate-details"><summary>查看完整时间依据</summary><p>${escapeHtml(radar.estimate_basis)}</p></details></article>
    </section>
    ${predictionLines(radar)}
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
    <section class="panel"><header><span class="eyebrow purple-text">SPECIAL RESET · PURPLE</span><h2>特殊额度事件与待核验预告</h2></header><div class="special-grid">${specialResets(radar)}${specialAnnouncements(radar)}</div></section>
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

function bindRetry(): void {
  document.querySelector<HTMLButtonElement>("#retry")?.addEventListener("click", () => void refresh());
}

async function render(data: DashboardData, warning = ""): Promise<void> {
  const currentRevision = ++routeRevision;
  const route = pageRoute();
  let content: string;
  if (route.page === "ops") {
    content = renderOps(data.health, warning);
  } else if (route.page === "invalid-history") {
    content = `<main><section class="panel prediction-history-page"><a class="back-link" href="#/">返回 Radar</a><h1>预测历史链接无效</h1><p role="status">请从某条预测线的“查看此系列历史”入口打开。</p></section></main>`;
  } else if (route.page === "history") {
    content = `<main><section class="panel"><p role="status">正在读取 ${escapeHtml(predictionTitles[route.target])} 的同系列版本…</p></section></main>`;
    app.innerHTML = shell(`${warning}${content}`, data.health.version);
    try {
      const history = await loadPredictionHistory(route.target, route.seriesId, route.limit);
      if (currentRevision !== routeRevision) return;
      content = renderHistoryPage(history, route.target, route.seriesId, warning);
    } catch (error) {
      if (currentRevision !== routeRevision) return;
      const message = error instanceof Error ? error.message : String(error);
      content = `${warning}${renderHistoryError(route.target, route.seriesId, message)}`;
    }
  } else {
    content = renderHome(data.radar, data.health, data.posts.items, warning);
  }
  app.innerHTML = shell(content, data.health.version);
  bindRetry();
}

async function refresh(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  if (!lastSuccessful) app.innerHTML = `<div class="loading-shell" role="status">正在读取本地 Backend API…</div>`;
  try {
    const data = await loadV2Dashboard();
    lastSuccessful = { data, receivedAt: new Date() };
    lastRefreshFailure = null;
    await render(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    lastRefreshFailure = message;
    if (lastSuccessful) {
      const receivedAt = lastSuccessful.receivedAt;
      const staleData: DashboardData = {
        ...lastSuccessful.data,
        radar: {
          ...lastSuccessful.data.radar,
          action_level: 'UNKNOWN', horizon_24h: 'UNKNOWN', horizon_48h: 'UNKNOWN', horizon_72h: 'UNKNOWN',
          judgement_state: 'invalid', reason_summary: '无法核验当前结果，Backend 刷新失败。',
          estimated_start: null, estimated_end: null, estimate_basis: '刷新失败，无法核验时间窗口。',
          prediction: downgradePredictionOnRefreshFailure(lastSuccessful.data.radar.prediction)
        }
      };
      lastSuccessful = { data: staleData, receivedAt };
      await render(staleData, refreshWarning(message, receivedAt));
    }
    else app.innerHTML = shell(`<main><section class="panel error-panel"><span class="eyebrow">BACKEND UNAVAILABLE</span><h1>本地 V2 Backend 暂不可用</h1><p>${escapeHtml(message)}</p><button type="button" id="retry">重新连接</button></section></main>`, "unavailable");
    bindRetry();
  } finally {
    refreshing = false;
  }
}

window.addEventListener("hashchange", () => lastSuccessful
  ? void render(lastSuccessful.data, lastRefreshFailure ? refreshWarning(lastRefreshFailure, lastSuccessful.receivedAt) : "")
  : void refresh());
void refresh();
window.setInterval(() => void refresh(), 60_000);
