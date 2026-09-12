import { describe, expect, it } from "vitest";
import { actionCopy, tone } from "./radar-ui";

describe("V2 product tones", () => {
  it("renders UNKNOWN as white rather than green", () => {
    expect(tone("UNKNOWN")).toBe("unknown");
    expect(actionCopy("UNKNOWN")).toContain("无法判断");
  });

  it("keeps the four action levels distinct", () => {
    expect(["GREEN", "YELLOW", "ORANGE", "RED"].map((value) => tone(value as never))).toEqual([
      "green", "yellow", "orange", "red"
    ]);
  });
});
