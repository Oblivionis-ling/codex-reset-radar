import type { NormalizedTweet, TweetSource } from "./types";

const STATUS_RE = /\/status\/(\d+)/;
const TIBO_STATUS_PATH_RE = /^\/thsottiaux\/status\/\d+$/i;

function clean(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function absoluteUrl(href: string): string {
  try {
    return new URL(href, window.location.origin).toString();
  } catch {
    return href;
  }
}

function handleFromHref(href: string): string | null {
  try {
    const url = new URL(href, "https://x.com");
    return url.pathname.split("/").filter(Boolean)[0]?.toLowerCase() ?? null;
  } catch {
    return null;
  }
}

function ownStatusLink(card: Element): HTMLAnchorElement | null {
  const time = Array.from(card.querySelectorAll<HTMLTimeElement>('time[datetime]'))
    .find(element => element.closest('article') === card && !element.closest('[data-testid="quoteTweet"]'));
  return time?.closest<HTMLAnchorElement>('a[href*="/status/"]') ?? null;
}

function extractId(card: Element): string | null {
  const link = ownStatusLink(card);
  const match = link?.getAttribute("href")?.match(STATUS_RE);
  return match?.[1] ?? null;
}

function isTiboCard(card: Element): boolean {
  return handleFromHref(ownStatusLink(card)?.getAttribute('href') ?? '') === 'thsottiaux';
}

function extractText(card: Element): string {
  const semantic = Array.from(card.querySelectorAll<HTMLElement>('[data-testid="tweetText"]'))
    .find(element => element.closest('article') === card && !element.closest('[data-testid="quoteTweet"], [role="link"]'));
  if (semantic) return clean(semantic.innerText || semantic.textContent);

  // X has changed Tweet text selectors several times. Remove nested quoted cards
  // and controls before using the remaining readable card text as a fallback.
  return ''; // UI chrome is never a replacement for a tweet body.
}

function extractReplyTarget(card: Element, tweetId: string): string | null {
  void card; void tweetId;
  return null; // Quote/status links and mentions do not prove replied_to.
}

function candidateCards(root: ParentNode): Element[] {
  const semantic = Array.from(root.querySelectorAll('[data-testid="tweet"]'));
  if (semantic.length > 0) return semantic;
  return Array.from(root.querySelectorAll("article"));
}

export function sourceForLocation(pathname: string, previousSource: TweetSource | null = null): TweetSource | null {
  const path = pathname.replace(/\/$/, "") || "/";
  if (path === "/thsottiaux") return "profile_dom";
  if (path === "/thsottiaux/with_replies") return "with_replies";
  if (path === "/search") return "search";
  if (TIBO_STATUS_PATH_RE.test(path) && (previousSource === "profile_dom" || previousSource === "with_replies")) {
    return previousSource;
  }
  return null;
}

export function extractTweets(root: ParentNode, source: TweetSource, discoveredAt = new Date()): NormalizedTweet[] {
  const seen = new Set<string>();
  const tweets: NormalizedTweet[] = [];
  for (const card of candidateCards(root)) {
    if (!isTiboCard(card)) continue;
    const tweetId = extractId(card);
    if (!tweetId || seen.has(tweetId)) continue;
    seen.add(tweetId);
    const time = card.querySelector<HTMLTimeElement>("time[datetime]");
    const replyTo = extractReplyTarget(card, tweetId);
    tweets.push({
      tweet_id: tweetId,
      author: "thsottiaux",
      text: extractText(card),
      created_at: time?.dateTime || time?.getAttribute("datetime") || null,
      url: absoluteUrl(`/thsottiaux/status/${tweetId}`),
      is_reply: source === "with_replies" || /replying to|回复|回应/i.test(card.textContent ?? '') || Boolean(replyTo),
      reply_to: replyTo,
      discovered_at: discoveredAt.toISOString(),
      source
    });
  }
  return tweets;
}
