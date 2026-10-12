#!/usr/bin/env python3
"""Test every cloud route and print PASS/FAIL per route. Run from this folder: python3 health.py [--no-youtube]
Targets are found fresh each run (search first, then read what came back) so the check doesn't rot when
one product or post disappears. Exit code = number of failed routes."""
import json, re, subprocess, sys, time, urllib.request

HERE = __file__.rsplit("/", 1)[0] or "."
RESULTS = []


def run(cmd, timeout=150):
    p = subprocess.run(cmd, shell=True, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    return p.stdout + p.stderr


def check(name, fn):
    t = time.time()
    for attempt in (1, 2):  # one retry: free services blip, and a single miss isn't a break
        try:
            ok, note = fn()
        except Exception as e:
            ok, note = False, f"{type(e).__name__}: {str(e)[:160]}"
        if ok: break
        time.sleep(5)
    RESULTS.append((name, ok, note, round(time.time() - t)))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<16} {round(time.time() - t):>3}s  {note}", flush=True)


def j(cmd):
    return json.loads(run(cmd))


def you():
    o = run('python3 web.py you "weather forecast"')
    n = o.count("\n## ") + o.startswith("## ")
    return n >= 3, f"{n} results"


def exa():
    o = run('python3 web.py exa "how to repot a houseplant"')
    n = o.count("URL:")
    return n >= 2, f"{n} results"


def jina():
    # example.com asks not to be used for monitoring, and Jina's cache once served a stale fake copy of it,
    # so read a stable Wikipedia article live (X-No-Cache) and check its own words come back.
    o = run('curl -s -m 40 -H "X-No-Cache: true" "https://r.jina.ai/https://en.wikipedia.org/wiki/Houseplant"')
    ok = "Title: Houseplant" in o and "orchid" in o.lower() and len(o) > 3000
    return ok, f"{len(o)} chars"


def amazon():
    o = run("""python3 -c "import web,re; print(' '.join(dict.fromkeys(re.findall(r'data-asin=\\"(B0\\w{8})\\"', web.get('https://www.amazon.com/s?k=usb+c+cable')))))" """)
    asins = o.split()[:3]
    if not asins: return False, "search page gave no ASINs: " + o[:120]
    for a in asins:
        d = j(f"python3 web.py amazon {a}")
        if d.get("price") and d.get("rating"):
            return True, f"{a}: price {d['price']}, {len(d.get('customers_say_by_topic') or [])} review topics"
    return False, f"no price/rating on {asins}: {str(d)[:120]}"


def target():
    d = j('python3 web.py target "tv" 3')
    return bool(d and d[0].get("price")), f"{len(d)} items, first {d[0].get('price') if d else None}"


def costco():
    o = run('python3 web.py exa "costco.com kirkland signature product"')
    ids = list(dict.fromkeys(re.findall(r"costco\.com/(?:p/[^ ]*?/|[^ ]*?\.product\.)(\d{6,})", o)))
    ids += ["100121461", "11072245"]  # long-running Kirkland items as a backstop
    for pid in ids[:6]:
        d = j(f"python3 web.py costco {pid} 1 5")
        if d.get("total"):
            return True, f"product {pid}: {d['total']} low-star reviews, average {round(d['average'] or 0, 2)}"
    return False, f"no reviews on any of {ids[:6]}"


def linkedin():
    d = j('python3 web.py jobs "manager" "United States"')
    if not d: return False, "0 jobs"
    p = j(f"python3 web.py job {d[0]['id']}")
    return bool(p.get("description")), f"{len(d)} jobs; posting text {len(p.get('description') or '')} chars"


def greenhouse():
    for co in ["stripe", "airbnb", "gitlab", "discord"]:
        try:
            d = j(f"python3 web.py greenhouse {co}")
            if d: return True, f"{co}: {len(d)} jobs"
        except Exception:
            continue
    return False, "no board answered"


def x():
    d = j("python3 web.py x 20")  # the first post on the site; it won't be deleted
    return "twttr" in (d.get("text") or ""), (d.get("text") or str(d))[:60]


def hn():
    d = j('python3 web.py hn "python"')
    return len(d) >= 5, f"{len(d)} comments"


def reddit():
    f = run("python3 reddit.py posts AskReddit --sort top --t week")
    if f.count(" votes | ") < 5: return False, "subreddit feed: " + f[:120]
    o = run('python3 reddit.py search "advice" --sort top --t month')
    urls = re.findall(r"https://www\.reddit\.com/r/\S+/comments/\S+", o)
    if not urls: return False, "search gave nothing: " + o[:120]
    t = run(f'python3 reddit.py thread "{urls[0]}" --max-calls 6', timeout=200)
    m = re.search(r"--- (\d+) comments read live", t)
    n = int(m.group(1)) if m else 0
    return n >= 5, f"feed ok; {len(urls)} threads found; {n} comments read from the top one"


def youtube():
    s = run("bash yt.sh setup", timeout=240)
    if "ready" not in s: return False, "setup: " + s[-160:]
    o = run('bash yt.sh search "news today" 3')
    ids = re.findall(r"^([\w-]{11}) \|", o, re.M)
    if not ids: return False, "search: " + o[-160:]
    for vid in ids:
        sub = run(f"bash yt.sh subs https://www.youtube.com/watch?v={vid} /tmp/hc_yt", timeout=200)
        if "saved" in sub:
            fr = run(f"bash yt.sh frame https://www.youtube.com/watch?v={vid} 30 /tmp/hc_frame.png")
            return "saved" in fr, sub.strip().splitlines()[-1][:80] + ("; frame ok" if "saved" in fr else "; FRAME FAILED " + fr[-80:])
    return False, "no captions on any of " + " ".join(ids)


CHECKS = [("search: you.com", you), ("search: exa", exa), ("read: jina", jina), ("amazon", amazon),
          ("target", target), ("costco reviews", costco), ("linkedin jobs", linkedin), ("greenhouse", greenhouse),
          ("x post", x), ("hacker news", hn), ("reddit", reddit), ("youtube", youtube)]

if __name__ == "__main__":
    skip = {"youtube"} if "--no-youtube" in sys.argv else set()
    print(f"health check {time.strftime('%Y-%m-%d %H:%M')}")
    for name, fn in CHECKS:
        if fn.__name__ not in skip:
            check(name, fn)
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} routes working" + (": broken " + ", ".join(r[0] for r in bad) if bad else ""))
    sys.exit(len(bad))
