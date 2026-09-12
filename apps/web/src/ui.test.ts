import { describe, expect, it } from "vitest";
import { ADVICE_LEVELS, RADAR_STATES, adviceTone, radarStateToken } from "./ui";

describe("Grid Ops state tokens", () => {
  it("keeps every Radar state renderable without changing the business enum", () => {
    expect(RADAR_STATES.slice(0, -1).map(radarStateToken)).toEqual([
      "quiet", "watch", "likely", "imminent", "announced", "confirmed"
    ]);
    expect(radarStateToken("unexpected_state")).toBe("unknown");
  });

  it("keeps every Usage Advice level renderable", () => {
    expect(ADVICE_LEVELS.map(adviceTone)).toEqual(["green", "yellow", "orange", "red"]);
    expect(adviceTone("not-a-level")).toBe("green");
  });
});
