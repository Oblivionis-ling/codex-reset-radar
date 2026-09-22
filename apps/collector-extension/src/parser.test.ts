import { beforeEach, describe, expect, it } from "vitest";
import { JSDOM } from "jsdom";
import { extractTweets, sourceForLocation } from "./parser";

function setDom(html: string): Document {
  const dom = new JSDOM(`<body>${html}</body>`, { url: "https://x.com/thsottiaux" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document });
  return dom.window.document;
}

describe("Tweet DOM parser", () => {
  beforeEach(() => setDom(""));

  it("extracts a Tibo Tweet and ignores a quoted non-Tibo article", () => {
    const document = setDom(`
      <article data-testid="tweet">
        <a href="/thsottiaux/status/100"><span>@thsottiaux</span><time datetime="2026-08-28T00:00:00.000Z">2h</time></a>
        <div data-testid="tweetText">Wonder if I can find that thing tomorrow...</div>
        <article><a href="/someone/status/99">quoted</a><div data-testid="tweetText">quoted text</div></article>
      </article>
      <article data-testid="tweet"><a href="/someone/status/99">@someone</a><div data-testid="tweetText">not Tibo</div></article>
    `);
    const tweets = extractTweets(document, "profile_dom", new Date("2026-08-28T01:00:00.000Z"));
    expect(tweets).toHaveLength(1);
    expect(tweets[0]).toMatchObject({ tweet_id: "100", author: "thsottiaux", text: "Wonder if I can find that thing tomorrow..." });
  });

  it("deduplicates nested semantic cards and marks replies", () => {
    const document = setDom(`
      <article data-testid="tweet">
        <a href="https://x.com/thsottiaux/status/101"><time datetime="2026-08-28T00:00:00Z">post</time></a>
        <span>Replying to @someone</span>
        <a href="https://x.com/someone/status/98">parent</a>
        <div data-testid="tweetText">reply text</div>
      </article>
      <article data-testid="tweet"><a href="/thsottiaux/status/101"><time datetime="2026-08-28T00:00:00Z">same</time></a><div data-testid="tweetText">reply text</div></article>
    `);
    const tweets = extractTweets(document, "with_replies");
    expect(tweets).toHaveLength(1);
    expect(tweets[0].is_reply).toBe(true);
    expect(tweets[0].reply_to).toBeNull(); // An arbitrary linked status is not replied_to.
  });

  it("does not promote generic UI text to a tweet body when selectors are absent", () => {
    const document = setDom(`
      <article>
        <a href="/thsottiaux/status/102"><time datetime="2026-08-28T02:00:00.000Z">1h</time></a>
        <div dir="auto">Fallback text from a changed X DOM</div>
      </article>
    `);
    const tweets = extractTweets(document, "profile_dom");
    expect(tweets[0]).toMatchObject({ tweet_id: "102", text: "" });
  });

  it("maps supported pages to collector sources", () => {
    expect(sourceForLocation("/thsottiaux")).toBe("profile_dom");
    expect(sourceForLocation("/thsottiaux/with_replies")).toBe("with_replies");
    expect(sourceForLocation("/search")).toBe("search");
    expect(sourceForLocation("/home")).toBeNull();
  });

  it("preserves Profile context while navigating to a Tibo status", () => {
    expect(sourceForLocation("/thsottiaux/status/123", "profile_dom")).toBe("profile_dom");
  });

  it("preserves Replies context while navigating to a Tibo status", () => {
    expect(sourceForLocation("/thsottiaux/status/123", "with_replies")).toBe("with_replies");
  });

  it("recognizes the Profile route when returning from a status", () => {
    expect(sourceForLocation("/thsottiaux", "profile_dom")).toBe("profile_dom");
  });

  it("recognizes the Replies route when returning from a status", () => {
    expect(sourceForLocation("/thsottiaux/with_replies", "with_replies")).toBe("with_replies");
  });

  it("does not guess a monitor for a directly opened Tibo status", () => {
    expect(sourceForLocation("/thsottiaux/status/123")).toBeNull();
  });

  it("does not preserve Profile context for another user's status", () => {
    expect(sourceForLocation("/other_user/status/123", "profile_dom")).toBeNull();
  });

  it("does not inherit search context for a Tibo status", () => {
    expect(sourceForLocation("/thsottiaux/status/123", "search")).toBeNull();
  });
});
