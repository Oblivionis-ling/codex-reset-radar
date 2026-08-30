import { describe, expect, it } from "vitest";
import {
  ageLabel,
  healthState,
  isDataStale,
  loadDashboardData,
  signalTweets,
  type FetchJson
} from "./data";

const NOW = Date.parse("2026-08-30T18:00:00Z");

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

describe("dashboard data", () => {
  it("resolves public-data URLs against a GitHub Pages base path", async () => {
    const requested: string[] = [];
    const fetcher: FetchJson = async (input) => {
      requested.push(String(input));
      return jsonResponse(input.toString().endsWith("tweets.json") ? [] : {});
    };

    await loadDashboardData(fetcher, "https://oblivionis-ling.github.io/codex-reset-radar/");

    expect(requested).toContain("https://oblivionis-ling.github.io/codex-reset-radar/public-data/index.json");
    expect(requested.every((url) => url.includes("/codex-reset-radar/public-data/"))).toBe(true);
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
    expect(isDataStale("2026-08-30T17:40:00Z", NOW)).toBe(false);
    expect(isDataStale("2026-08-30T17:00:00Z", NOW)).toBe(true);
    expect(signalTweets([])).toEqual([]);
    expect(healthState(undefined, NOW)).toBe("unknown");
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
