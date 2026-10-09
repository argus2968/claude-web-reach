#!/usr/bin/env python3
"""Read live Reddit through the background endpoints reddit.com's own site uses.

  reddit.py search "query" [--sub SUBREDDIT] [--sort top] [--t year] [--pages 2]
  reddit.py posts SUBREDDIT [--sort top|hot|new] [--t year] [--pages 2]
  reddit.py thread SUBREDDIT POST_ID            # or a full thread URL
No login, no key. Stdlib only. One request about every 1.2 s.
"""
import argparse, html, json, re, sys, time, urllib.parse, urllib.request
from html.parser import HTMLParser

BASE = "https://www.reddit.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
PAUSE = 1.2
_last = [0.0]
CALLS = [0]


def get(path, post=None):
    """GET, or POST with a form-encoded body when post is a string."""
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = path if path.startswith("http") else BASE + path
    hdrs = {"User-Agent": UA, "Accept-Language": "en-US"}
    if post is not None:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=post.encode() if post is not None else None, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                _last[0] = time.time(); CALLS[0] += 1
                return r.read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            _last[0] = time.time(); CALLS[0] += 1
            if e.code == 429 and attempt < 2:
                time.sleep(10 * (attempt + 1)); continue
            if e.code == 404:
                raise SystemExit(f"HTTP 404 from {url}  (bad URL or ID, or the post was deleted; the route itself is fine)")
            raise SystemExit(f"HTTP {e.code} from {url}  (Reddit may have closed this route)")
    raise SystemExit("gave up")


def attrs_of(tag_text):
    return {k: html.unescape(v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', tag_text)}


def text_of(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</p>|</li>", "\n", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


class CommentParser(HTMLParser):
    """Collects <shreddit-comment> attributes plus the text of its slot=comment div."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.comments, self.partials = [], []
        self.stack, self.cur, self.depth, self.buf = [], None, 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "shreddit-comment":
            self.stack.append(a)
        elif tag == "faceplate-partial" and "/more-comments/" in (a.get("src") or ""):
            self.partials.append(a["src"])
        if self.cur is not None:
            if tag == "div": self.depth += 1
            if tag in ("p", "br", "li"): self.buf.append("\n")
        elif tag == "div" and a.get("slot") == "comment" and self.stack:
            self.cur, self.depth, self.buf = self.stack[-1], 1, []

    def handle_endtag(self, tag):
        if self.cur is not None and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                c = dict(self.cur); c["body"] = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", "".join(self.buf))).strip()
                self.comments.append(c); self.cur = None
        if tag == "shreddit-comment" and self.stack:
            top = self.stack.pop()
            if not any(x.get("thingid") == top.get("thingid") for x in self.comments):
                c = dict(top); c["body"] = "[no text: image, removed or deleted]"; self.comments.append(c)

    def handle_data(self, d):
        if self.cur is not None: self.buf.append(d)


def parse_comments(page):
    """Returns comments plus 'load more' requests as (path, form) pairs; the form carries Reddit's cursor."""
    p = CommentParser(); p.feed(page)
    more = []
    for src, inner in re.findall(r'<faceplate-partial[^>]*src="(/svc/shreddit/more-comments/[^"]+)"[^>]*>(.*?)</faceplate-partial>', page, re.S):
        form = {n: html.unescape(v) for n, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', inner)}
        more.append((html.unescape(src), urllib.parse.urlencode(form)))
    return p.comments, more


def parse_page(page):
    """Comments, 'load more' requests, and comments whose replies Reddit cut off ('N more replies' links)."""
    cs, more = parse_comments(page)
    cut = set(re.findall(r'/comment/(\w+)/[^"]*"[^>]*slot="more-comments-permalink"(?:(?!</a>).)*?noun="more_replies"', page, re.S))
    return cs, more, {"t1_" + c for c in cut}


MAX_NEST = 4  # Reddit's web view stops nesting at depth 4 and links out for deeper replies


def thread(sub, pid, max_calls=150):
    """Whole comment tree: first page, every 'load more' batch, and every reply chain deeper than Reddit nests."""
    seen, out, done = set(), [], set()
    # queue items: (path, form or None, depth offset)
    queue = [(f"/svc/shreddit/comments/r/{sub}/t3_{pid}", None, 0)]
    expanded, cut_all = set(), set()
    calls = 0

    def run():
        nonlocal calls
        while queue and calls < max_calls:
            path, form, off = queue.pop(0)
            if (path, form) in done: continue
            done.add((path, form))
            cs, more, cut = parse_page(get(path, post=form)); calls += 1
            cut_all.update(cut)
            for c in cs:
                c["depth"] = str(int(c.get("depth", 0) or 0) + off)
                if c["thingid"] in seen: continue
                seen.add(c["thingid"]); out.append(c)
            queue.extend((s, f, off) for s, f in more)
            for c in out:   # chains deeper than Reddit nests
                d = int(c["depth"])
                if d >= MAX_NEST and (d - MAX_NEST) % MAX_NEST == 0 and c["thingid"] not in expanded:
                    expanded.add(c["thingid"])
                    queue.append((f"/svc/shreddit/comments/r/{sub}/t3_{pid}/{c['thingid']}", None, d))

    run()
    # Second pass: comments labelled "N more replies" whose replies never arrived.
    for _ in range(3):
        parents = {c.get("parentid") for c in out}
        todo = [c for c in out if c["thingid"] in cut_all and c["thingid"] not in parents and c["thingid"] not in expanded]
        if not todo: break
        for c in todo:
            expanded.add(c["thingid"])
            queue.append((f"/svc/shreddit/comments/r/{sub}/t3_{pid}/{c['thingid']}", None, int(c["depth"])))
        run()
    return out, len(queue)


def order_tree(comments):
    kids, roots = {}, []
    for c in comments:
        (kids.setdefault(c.get("parentid"), []) if c.get("parentid") else roots).append(c)
    ordered = []
    def walk(c):
        ordered.append(c)
        for k in kids.get(c["thingid"], []): walk(k)
    for r in roots: walk(r)
    orphans = [c for c in comments if c not in ordered]
    return ordered + orphans


def post_meta(sub, pid):
    """The post itself. Reddit has no single-post address that answers, so: the Arctic Shift archive
    (retrying when it throttles), then the subreddit's live 'new' feed for posts too fresh for the archive."""
    url = f"https://arctic-shift.photon-reddit.com/api/posts/ids?ids={pid}&fields=title,selftext,score,num_comments,created_utc,author,url"
    for wait in (0, 5, 15):
        time.sleep(wait)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40))
            if d.get("data"):
                m = d["data"][0]; m["source"] = "archive"; return m
            if "many requests" not in str(d.get("error", "")).lower():
                break
        except Exception:
            pass
    try:
        for p in posts(sub, "new", None, 3):
            if p["id"] == pid:
                return {"title": p["title"], "selftext": p["body"] or p["link"], "score": p["score"],
                        "num_comments": p["comments"], "author": "", "source": "live new-posts feed"}
    except SystemExit:
        pass
    return None


def parse_search(page):
    res = []
    for m in re.finditer(r'id="search-post-title-(t3_\w+)" href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=id="search-post-title-|\Z)', page, re.S):
        tid, href, title, rest = m.groups()
        nums = re.findall(r'number="(\d+)"[^<]*</faceplate-number>\s*(votes?|comments?)', rest[:3000])
        n = {k.rstrip("s"): int(v) for v, k in nums}
        ts = re.findall(r'ts="([^"]+)"', page[max(0, m.start() - 4000):m.start()])
        sr = re.search(r"/r/([^/]+)/comments/", href)
        res.append({"id": tid[3:], "title": text_of(title), "sub": sr.group(1) if sr else "",
                    "votes": n.get("vote"), "comments": n.get("comment"),
                    "date": ts[-1][:10] if ts else "", "url": BASE + html.unescape(href)})
    nxt = re.search(r'src="(/svc/shreddit/(?:r/[^/]+/)?search/[^"]*cursor=[^"]+)"', page)
    return res, html.unescape(nxt.group(1)) if nxt else None


LOCAL_SORT = {"top": lambda r: -(r["votes"] or 0), "comments": lambda r: -(r["comments"] or 0),
              "new": lambda r: "".join(chr(255 - ord(ch)) for ch in r["date"])}


def search(q, sub=None, sort=None, t=None, pages=1):
    """Since Oct 2026 Reddit answers logged-out searches sorted by top/new/comments with 'no results'; only
    relevance works (the time window t still works). So for those sorts: fetch 3x the pages by relevance and sort here."""
    qs = {"q": q, "type": "link"}
    local = LOCAL_SORT.get(sort)
    if sort and not local: qs["sort"] = sort
    if local: pages *= 3
    if t: qs["t"] = t
    path = (f"/svc/shreddit/r/{sub}/search/" if sub else "/svc/shreddit/search/") + "?" + urllib.parse.urlencode(qs)
    out, ids = [], set()
    for _ in range(pages):
        res, nxt = parse_search(get(path))
        for r in res:
            if r["id"] not in ids: ids.add(r["id"]); out.append(r)
        if not nxt: break
        path = nxt
    if local:
        out.sort(key=local)
    return out


def parse_posts(page):
    out = []
    for a, inner in re.findall(r"<shreddit-post\s([^>]*)>(.*?)</shreddit-post>", page, re.S):
        d = attrs_of(a)
        if "is-ad" in a or "promoted" in a.split("post-title")[0]:
            continue
        body = ""
        i = inner.find('slot="text-body"')
        if i >= 0:
            seg = inner[i:]; body = text_of(seg[seg.find(">") + 1:])
        out.append({"id": d.get("id", "")[3:], "title": d.get("post-title", ""), "score": d.get("score"),
                    "comments": d.get("comment-count"), "date": d.get("created-timestamp", "")[:10],
                    "type": d.get("post-type"), "url": BASE + d.get("permalink", ""),
                    "link": d.get("content-href", ""), "body": body})
    nxt = re.search(r'src="(/svc/shreddit/community-more-posts/[^"]*after=[^"]+)"', page)
    return out, html.unescape(nxt.group(1)) if nxt else None


def posts(sub, sort="hot", t=None, pages=1):
    path = f"/svc/shreddit/community-more-posts/{sort}/?" + urllib.parse.urlencode({"name": sub, **({"t": t.upper()} if t else {})})
    out, ids = [], set()
    for _ in range(pages):
        res, nxt = parse_posts(get(path))
        for r in res:
            if r["id"] not in ids: ids.add(r["id"]); out.append(r)
        if not nxt: break
        path = nxt
    return out


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("search"); s.add_argument("q"); s.add_argument("--sub"); s.add_argument("--sort"); s.add_argument("--t"); s.add_argument("--pages", type=int, default=1)
    p = sp.add_parser("posts"); p.add_argument("sub"); p.add_argument("--sort", default="hot"); p.add_argument("--t"); p.add_argument("--pages", type=int, default=1); p.add_argument("--full", action="store_true")
    th = sp.add_parser("thread"); th.add_argument("sub_or_url"); th.add_argument("id", nargs="?"); th.add_argument("--max-calls", type=int, default=150); th.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.cmd == "search":
        res = search(a.q, a.sub, a.sort, a.t, a.pages)
        if not res:
            print("0 RESULTS. If the query is common, Reddit may have changed its pages and this script can no longer read them.")
        for r in res:
            print(f"{r['votes']} votes | {r['comments']} comments | {r['date']} | r/{r['sub']} | {r['title']} | {r['url']}")
    elif a.cmd == "posts":
        res = posts(a.sub, a.sort, a.t, a.pages)
        if not res:
            print("0 POSTS. Check the subreddit name; if it's right, Reddit may have changed its pages.")
        for r in res:
            print(f"\n## {r['title']}\n{r['score']} votes | {r['comments']} comments | {r['date']} | {r['type']} | {r['url']}")
            if r["body"]: print(r["body"] if a.full else r["body"][:400] + ("..." if len(r["body"]) > 400 else ""))
            elif r["link"]: print(r["link"])
    else:
        if a.id is None:
            m = re.search(r"/r/([^/]+)/comments/(\w+)", a.sub_or_url)
            if not m: raise SystemExit("give SUB ID or a thread URL")
            sub, pid = m.groups()
        else:
            sub, pid = a.sub_or_url, a.id
        cs, left = thread(sub, pid, a.max_calls)
        cs = order_tree(cs)
        meta = post_meta(sub, pid)
        if a.json:
            print(json.dumps({"post": meta, "comments": cs, "unfetched_batches": left}, ensure_ascii=False)); return
        if meta:
            by = f"by u/{meta['author']} | " if meta.get("author") else ""
            print(f"# {meta.get('title')}\n{by}post text from the {meta['source']}; comment count there: {meta.get('num_comments')}\n\n{meta.get('selftext','')}\n")
        else:
            slug = re.search(r"/comments/\w+/([^/?#]+)", a.sub_or_url)
            print(f"# POST TEXT UNAVAILABLE (archive missing or throttled, and not in the subreddit's 3 newest pages)\n"
                  f"Title from the link: {slug.group(1).replace('_', ' ') if slug else '(no title in link)'}\n")
        print(f"--- {len(cs)} comments read live from Reddit, {CALLS[0]} requests, {left} batches not fetched ---\n")
        if not cs and meta and str(meta.get("num_comments") or "0") not in ("0", "None"):
            print("0 COMMENTS READ, but the post has comments: Reddit may have changed its pages. Treat the live route as broken.\n")
        for c in cs:
            d = int(c.get("depth", 0) or 0)
            op = " [OP]" if "is-op" in c else ""
            print(f"{'    ' * d}- [{c.get('score')}] u/{c.get('author')}{op} ({c.get('created','')[:10]}): {c['body']}")


if __name__ == "__main__":
    main()