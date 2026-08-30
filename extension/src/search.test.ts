import { describe, expect, it } from "vitest";
import { buildSearchUrls } from "./search";

describe("X search backfill windows", () => {
  it("covers full UTC containing days for a 72-hour pass", () => {
    const urls = buildSearchUrls(new Date("2026-08-28T12:34:00Z"), 72);
    expect(urls).toHaveLength(4);
    expect(urls[0]).toContain("from%3Athsottiaux%20since%3A2026-08-25%20until%3A2026-08-26");
    expect(urls.at(-1)).toContain("since%3A2026-08-28%20until%3A2026-08-29");
    expect(urls.every((url) => url.endsWith("&f=live"))).toBe(true);
  });
});

