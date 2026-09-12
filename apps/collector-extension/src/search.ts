export function buildSearchUrls(now = new Date(), hours = 72): string[] {
  const currentDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const firstDay = new Date(currentDay);
  firstDay.setUTCDate(firstDay.getUTCDate() - Math.ceil(hours / 24));
  const urls: string[] = [];

  // Include the current UTC day because X's `until` boundary is exclusive.
  // This intentionally scans complete containing days around the exact window.
  for (const cursor = new Date(firstDay); cursor <= currentDay; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    const until = new Date(cursor);
    until.setUTCDate(until.getUTCDate() + 1);
    const query = `from:thsottiaux since:${cursor.toISOString().slice(0, 10)} until:${until.toISOString().slice(0, 10)}`;
    urls.push(`https://x.com/search?q=${encodeURIComponent(query)}&src=typed_query&f=live`);
  }
  return urls;
}

