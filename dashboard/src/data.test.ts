import { describe, expect, it } from "vitest";
import {
  ageLabel,
  deriveDataFreshness,
  deriveDisplayHealth,
  deriveMirrorState,
  isDataStale,
  loadDashboardData,
  mergeDashboardData,
  signalTweets,
  type FetchJson
} from "./data";

const NOW = Date.parse("2026-08-30T18:00:00Z");

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

describe("dashboard data", () => {
  it("resolves data branch URLs against a raw GitHub base path", async () => {
    const requested: string[] = [];
    const initValues: RequestInit[] = [];
    const fetcher: FetchJson = async (input, init) => {
      requested.push(String(input));
      initValues.push(init ?? {});
      return jsonResponse(input.toString().endsWith("tweets.json") ? [] : {});
    };

    await loadDashboardData(fetcher, "https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/");

    expect(requested).toContain("https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/index.json");
    expect(requested.every((url) => url.includes("/codex-reset-radar/refs/heads/data/"))).toBe(true);
    expect(initValues).toHaveLength(6);
    expect(initValues.every((init) => init.cache === "no-store")).toBe(true);
  });

  it("parses mirror metadata and preserves the last successful file on refresh failure", async () => {
    const fetcher: FetchJson = async (input) => {
      if (input.toString().endsWith("meta.json")) {
        return jsonResponse({
          schema_version: 1,
          generated_at: "2026-08-30T17:59:00Z",
          mirror_synced_at: "2026-08-30T17:59:00Z"
        });
      }
      return jsonResponse(input.toString().endsWith("tweets.json") ? [{ tweet_id: "first" }] : {});
    };
    const previous = await loadDashboardData(fetcher, "https://example.test/data/");
    const failed: FetchJson = async (input) => {
      if (input.toString().endsWith("health.json")) throw new Error("network down");
      return jsonResponse(input.toString().endsWith("tweets.json") ? [{ tweet_id: "second" }] : {});
    };
    const next = await loadDashboardData(failed, "https://example.test/data/");
    const merged = mergeDashboardData(previous, next);

    expect(previous.meta?.mirror_synced_at).toBe("2026-08-30T17:59:00Z");
    expect(merged.tweets[0]?.tweet_id).toBe("second");
    expect(merged.health).toBe(previous.health);
    expect(merged.errors).toContain("health: network down");
  });

  it("does not throw when one public-data request fails", async () => {
    const fetcher: FetchJson = async (input) => {
      if (input.toString().endsWith("health.json")) throw new Error("offline");
      return jsonResponse([]);
    };

    const data = await loadDashboardData(fetcher, "https://example.test/codex-reset-radar/");

    expect(data.health).toBeNull();
    expect(data.errors).toContain("health: offline");
  });

  it("handles stale data, empty signals, and a missing health component", () => {
    expect(isDataStale("2026-08-30T17:58:00Z", NOW)).toBe(false);
    expect(isDataStale("2026-08-30T17:40:00Z", NOW)).toBe(true);
    expect(signalTweets([])).toEqual([]);
    const healthy = { component: "profile_monitor", state: "healthy", last_heartbeat: "2026-08-30T17:57:00Z" };
    const offline = { component: "profile_monitor", state: "offline", last_heartbeat: "2026-08-30T17:57:00Z" };
    expect(deriveDisplayHealth(healthy, "2026-08-30T17:57:00Z", NOW)).toBe("healthy");
    expect(deriveDisplayHealth(offline, "2026-08-30T17:57:00Z", NOW)).toBe("offline");
    expect(deriveDisplayHealth(healthy, "2026-08-30T17:40:00Z", NOW)).toBe("stale");
    expect(deriveDisplayHealth(offline, "2026-08-30T17:40:00Z", NOW)).toBe("stale");
    expect(deriveDisplayHealth(undefined, "2026-08-30T17:57:00Z", NOW)).toBe("unknown");
    expect(deriveDisplayHealth(healthy, undefined, NOW)).toBe("unknown");
    expect(deriveDataFreshness("2026-08-30T17:58:00Z", NOW)).toBe("fresh");
    expect(deriveDataFreshness("2026-08-30T17:40:00Z", NOW)).toBe("stale");
    expect(deriveDataFreshness(undefined, NOW)).toBe("unknown");
    expect(deriveMirrorState("2026-08-30T17:59:00Z", NOW)).toBe("fresh");
    expect(deriveMirrorState("2026-08-30T17:40:00Z", NOW)).toBe("stale");
    expect(deriveMirrorState("not-a-date", NOW)).toBe("unknown");
    expect(ageLabel("2026-08-30T17:59:00Z", NOW)).toBe("1m ago");
    expect(ageLabel("2026-08-30T17:59:00Z", NOW, "zh")).toBe("1 分钟前");
  });

  it("weakens quota information without dropping reset signals", () => {
    const tweets = [
      { created_at: "2026-08-30T17:00:00Z", classification: { category: "quota_information" } },
      { created_at: "2026-08-30T16:00:00Z", classification: { category: "reset_hint" } },
      { created_at: "2026-08-30T15:00:00Z", classification: { category: "unrelated" } }
    ];
    expect(signalTweets(tweets).map((tweet) => tweet.classification?.category)).toEqual([
      "quota_information",
      "reset_hint"
    ]);
  });
});
