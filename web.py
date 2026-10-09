#!/usr/bin/env python3
"""Cloud web routes tested Oct 9, 2026 from Claude's sandbox. Plain HTTP, no logins, no keys.
  python3 web.py you "query"              You.com search, 10 results with long extracts (~100/day)
  python3 web.py exa "query"              Exa search, 5 results with page text
  python3 web.py amazon ASIN              price, stock, rating, star split, "bought in past month", per-topic review summary
  python3 web.py target "query" [n]       Target search with prices
  python3 web.py costco PRODUCT_ID [2]    Costco member reviews, star split; optional 2 = only 1-2 star
  python3 web.py jobs "title" "City, State" [start]   LinkedIn job search, logged out
  python3 web.py job JOB_ID               full LinkedIn posting, logged out
  python3 web.py greenhouse COMPANY       every open job on a Greenhouse board (COMPANY = the slug in its boards URL)
  python3 web.py x POST_ID                one X post (text, date, likes)
  python3 web.py hn "query"               Hacker News comment search
"""
import base64, gzip, html, json, re, sys, urllib.error, urllib.parse, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"

def get(url):
    # Amazon serves a captcha when Accept is missing: keep full browser-like headers.
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en-US",
        "Accept-Encoding": "gzip"}), timeout=30)
    b = r.read()
    return (gzip.decompress(b) if r.headers.get("Content-Encoding") == "gzip" else b).decode("utf8", "replace")

def text(h): return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", h))).strip()

def mcp(url, body, sid=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "mcp-client/1.0"}
    if sid: h["Mcp-Session-Id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=h), timeout=60)
    return r.headers.get("Mcp-Session-Id"), r.read().decode()

def result_text(raw):
    for line in raw.splitlines():
        if line.startswith("data:") and '"result"' in line:
            return json.loads(line[5:])["result"]["content"][0]["text"]
    if raw.lstrip().startswith("{"):
        d = json.loads(raw)
        if "result" in d: return d["result"]["content"][0]["text"]
    return None

def you(*q):
    _, raw = mcp("https://api.you.com/mcp?profile=free", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "you-search", "arguments": {"query": " ".join(q), "count": 10}}})
    t = result_text(raw)
    if not t: return f"NO RESULTS PARSED. Raw reply: {raw[:400]}"
    out = []
    for r in json.loads(t).get("results", {}).get("web", []):
        out.append(f"## {r['title']}\n{r['url']} ({r.get('page_age', '')[:10]})")
        out += ["- " + h.replace("\n", " ")[:400] for h in r.get("contents", {}).get("highlights", [])[:3]]
    return "\n".join(out) or "0 results"

def exa(*q):
    u = "https://mcp.exa.ai/mcp"
    sid, _ = mcp(u, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18",
        "capabilities": {}, "clientInfo": {"name": "web", "version": "1"}}})
    mcp(u, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, raw = mcp(u, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "web_search_exa",
        "arguments": {"query": " ".join(q), "numResults": 5}}}, sid)
    return result_text(raw) or f"NO RESULTS PARSED. Raw reply: {raw[:400]}"

def amazon(asin):
    s = get(f"https://www.amazon.com/dp/{asin}")
    if "captcha" in s.lower(): return {"error": "Amazon served a captcha page"}
    if len(s) < 5000: return {"error": "page not found or empty"}
    g = lambda pat, f=re.S: (lambda m: m and html.unescape(m.group(1)).strip())(re.search(pat, s, f))
    out = {"asin": asin, "title": g(r'id="productTitle"[^>]*>\s*(.*?)\s*<'),
           "price": g(r'"priceAmount":([0-9.]+)') or g(r'id="corePrice(?:Display_desktop)?_feature_div".{0,3000}?class="a-offscreen">\$([0-9,.]+)<'),
           "stock": g(r'id="availability".{0,300}?<span[^>]*>\s*([^<]+)'),
           "rating": g(r'id="acrPopover"[^>]*title="([^"]+)"'),
           "ratings_count": (g(r'id="acrCustomerReviewText"[^>]*>([^<]+)<') or "").strip("() ") or None,
           "stars_percent": {f"{k}_star": int(v) for v, k in re.findall(r'aria-label="(\d+) percent of reviews have (\d) stars?"', s)},
           "bought": g(r'([0-9.,]+K?\+? bought in past month)')}
    aspects = []
    for c in re.findall(r'k-injected k\+b64 ([A-Za-z0-9+/=]+)', s):
        d = base64.b64decode(c + "=" * (-len(c) % 4)).decode("utf8", "replace")
        if "aspectsFlattened" in d:
            aspects = [{"sentiment": a.get("sentiment"), "summary": a.get("summary")} for a in json.loads(d)["k-data"]["aspectsFlattened"]]
            break
    out["customers_say_by_topic"] = aspects
    out["review_text"] = "needs sign-in: read reviews in a signed-in browser"
    return out

def target(query, n=5):
    q = urllib.parse.quote(query)
    d = json.loads(get("https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2?keyword=" + q + "&channel=WEB&count=" + str(n) +
        "&default_purchasability_filter=true&page=%2Fs%2F" + q + "&pricing_store_id=3991&visitor_id=0&key=9f36aeafbe60771e321a7cc95a78140772ab3e96"))
    return [{"tcin": p.get("tcin"), "title": html.unescape(p["item"]["product_description"]["title"]),
             "price": p.get("price", {}).get("formatted_current_price"), "url": f"https://www.target.com/p/-/A-{p.get('tcin')}"}
            for p in d["data"]["search"]["products"]]

def jobs(keywords, location, start=0):
    s = get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" +
            urllib.parse.urlencode({"keywords": keywords, "location": location, "start": start}))
    out = []
    for card in re.split(r'(?=<li>)', s):
        jid = re.search(r'urn:li:jobPosting:(\d+)', card)
        if not jid: continue
        g = lambda cls: (lambda m: text(m.group(1)) if m else None)(re.search(cls + r'[^>]*>(.*?)</', card, re.S))
        t = re.search(r'<time[^>]*datetime="([^"]+)"', card)
        out.append({"id": jid.group(1), "title": g("base-search-card__title"), "company": g("base-search-card__subtitle"),
                    "location": g("job-search-card__location"), "posted": t and t.group(1),
                    "url": f"https://www.linkedin.com/jobs/view/{jid.group(1)}"})
    return out

def job(job_id):
    s = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    d = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', s, re.S)
    title = re.search(r'top-card-layout__title[^>]*>(.*?)</', s, re.S)
    return {"id": job_id, "title": title and text(title.group(1)),
            "criteria": [text(x) for x in re.findall(r'description__job-criteria-text[^>]*>(.*?)</span>', s, re.S)],
            "description": d and re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<br\s*/?>|</p>|</li>", "\n",
                           re.sub(r"<(?!br|/p|/li)[^>]+>", "", d.group(1))))).strip()}

def greenhouse(company):
    d = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"))
    return [{"id": j["id"], "title": j["title"], "location": j["location"]["name"], "updated": j["updated_at"], "url": j["absolute_url"]} for j in d["jobs"]]

def x(post_id):
    d = json.loads(get(f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=4"))
    return {"id": post_id, "user": d.get("user", {}).get("screen_name"), "date": d.get("created_at"), "text": d.get("text"),
            "likes": d.get("favorite_count"), "replies": d.get("conversation_count")}

def hn(*q):
    d = json.loads(get("https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": " ".join(q), "tags": "comment", "hitsPerPage": 15})))
    return [{"author": h["author"], "date": h["created_at"][:10], "story": h.get("story_title"), "text": text(h.get("comment_text") or "")[:600],
             "url": f"https://news.ycombinator.com/item?id={h['objectID']}"} for h in d["hits"]]

def costco(pid, low=None, n=100):
    """Costco member reviews via Bazaarvoice, the service Costco's pages load them from. pid = the long number in
    the product URL (.product.<id>.html or /<id>). low=2 keeps only 1-2 star reviews."""
    q = [("resource", "reviews"), ("action", "REVIEWS_N_STATS"), ("filter", f"productid:eq:{pid}"), ("filter", "contentlocale:eq:en_US"),
         ("filter", "isratingsonly:eq:false")] + ([("filter", f"rating:lte:{low}")] if low else []) + [
         ("filter_reviews", "contentlocale:eq:en_US"), ("include", "products"), ("filteredstats", "reviews"), ("Stats", "Reviews"),
         ("limit", n), ("offset", 0), ("sort", "submissiontime:desc"), ("apiversion", "5.5"), ("displaycode", "2070_2_0")]
    r = urllib.request.Request("https://apps.bazaarvoice.com/bfd/v1/clients/Costco/api-products/cv2/resources/data/reviews.json?" + urllib.parse.urlencode(q),
        headers={"bv-bfd-token": "2070,main_site,en_US", "Origin": "https://www.costco.com", "Referer": "https://www.costco.com/", "User-Agent": UA})
    d = json.load(urllib.request.urlopen(r, timeout=30))["response"]
    st = (list(d.get("Includes", {}).get("Products", {}).values()) or [{}])[0].get("ReviewStatistics", {})
    return {"total": d["TotalResults"], "average": st.get("AverageOverallRating"),
            "stars": {x["RatingValue"]: x["Count"] for x in st.get("RatingDistribution", [])},
            "reviews": [{"date": x["SubmissionTime"][:10], "rating": x["Rating"], "title": x["Title"], "text": x["ReviewText"],
                         "helpful": x.get("TotalPositiveFeedbackCount")} for x in d["Results"]]}

if __name__ == "__main__":
    cmds = {f.__name__: f for f in (you, exa, amazon, target, costco, jobs, job, greenhouse, x, hn)}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds: sys.exit(__doc__)
    try:
        res = cmds[sys.argv[1]](*sys.argv[2:])
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {e.url}  (429 = rate limit, wait or switch tools; 403 = this route may have closed)")
    print(res if isinstance(res, str) else json.dumps(res, indent=1, ensure_ascii=False))