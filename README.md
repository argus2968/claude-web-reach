# claude-web-reach

Free, no-login web access for AI agents working from a cloud sandbox. Web search, exact page text, live Reddit threads, YouTube transcripts, comments and frames, store prices and reviews, and job listings, all from plain Python with no API keys and no accounts.

Built for Claude's cloud sandbox, where many sites block datacenter traffic and the built-in fetch tool summarizes pages instead of returning them. It works from any Linux machine with Python 3 and outbound HTTPS.

## Why it exists

An agent sent to "find out what owners say about X" usually gets a search snippet and a guess. The sources that answer the question (Reddit threads, YouTube reviews, store reviews) block cloud servers, hide behind JavaScript, or come back summarized. It reads them directly by using the same background requests each site's own pages make to load their data. It takes no logins and gets around no paywalls.

## What works

Every route below was tested from a Claude cloud sandbox in October 2026. `health.py` re-tests all of them on demand.

| Need | Command | Returns |
| --- | --- | --- |
| Web search | `python3 web.py you "query"` | 10 results with long page extracts |
| Web search, second engine | `python3 web.py exa "query"` | 5 results with page text |
| Exact page text | `curl -s "https://r.jina.ai/<url>"` | the page as clean text, word for word |
| Reddit search | `python3 reddit.py search "query" [--sub NAME] [--t week\|month\|year]` | threads with votes, comment counts, dates |
| Subreddit feed | `python3 reddit.py posts NAME --sort top\|new\|hot [--t week]` | posts with text, votes, comments |
| Whole Reddit thread | `python3 reddit.py thread <url> > thread.md` | every comment, nested, with scores |
| YouTube search | `bash yt.sh search "query" [N]` | video ids, titles, channels, lengths |
| YouTube transcript | `bash yt.sh subs <url> name` | `name.txt`, one timestamped line per caption |
| YouTube details | `bash yt.sh info <url>` | title, channel, date, views, full description with links |
| YouTube comments | `bash yt.sh comments <url> [N]` | top comments with like counts |
| YouTube frame | `bash yt.sh frame <url> SECONDS out.png` | still image at that moment (320x180) |
| Amazon product | `python3 web.py amazon ASIN` | price, stock, rating, star breakdown, "bought in past month", per-topic review summary |
| Target prices | `python3 web.py target "query"` | products with current prices |
| Costco reviews | `python3 web.py costco PRODUCT_ID [2]` | all member reviews and star breakdown; `2` keeps only 1-2 star |
| LinkedIn job search | `python3 web.py jobs "title" "City, State"` | job ids, titles, companies, locations, dates |
| LinkedIn job posting | `python3 web.py job JOB_ID` | full description and criteria |
| Greenhouse job board | `python3 web.py greenhouse COMPANY` | every open role at that company |
| One X post | `python3 web.py x POST_ID` | text, date, likes, replies |
| Hacker News | `python3 web.py hn "query"` | matching comments with links |

## Quick start

```bash
git clone --depth 1 https://github.com/argus2968/claude-web-reach && cd claude-web-reach
python3 web.py                 # list the web commands
python3 reddit.py --help       # Reddit commands
bash yt.sh setup               # YouTube only: installs yt-dlp and starts a local token server (~15 s)
python3 health.py              # test every route
```

`web.py` and `reddit.py` use only the Python standard library. YouTube needs Node.js (preinstalled in Claude's sandbox) plus the packages `yt.sh setup` installs. `yt.sh frame` needs Pillow.

## Health check

```text
$ python3 health.py
PASS  search: you.com    1s  10 results
PASS  amazon             3s  price 9.99, 8 review topics
PASS  reddit           100s  feed ok; 20 threads found; 33 comments read from the top one
PASS  youtube           23s  saved transcript (901 lines); frame ok
...
12/12 routes working
```

Each run finds its test targets fresh (it searches first, then reads what came back), so the check doesn't fail just because one product or post disappeared. Each route gets one retry before it counts as broken. The exit code is the number of broken routes, so a scheduled job can act on it.

## Limits

- **These are undocumented routes.** Sites change them without notice. That's what the health check is for.
- **Logged-out data only.** Amazon review text, X search and anything behind a login are out of scope. Agents that need those should use a browser the person is signed into.
- **Reddit:** sorting search results by top, new or comments currently returns nothing for logged-out visitors, so the script fetches by relevance and sorts locally. Subreddit feeds sort normally. Whole threads typically come back with 96-100% of the comments Reddit counts; the rest are image-only or deleted. The post's own text comes from the Arctic Shift archive, or from the subreddit's live feed for very new posts.
- **YouTube:** frames are 320x180, from YouTube's preview sheets. Downloading the video itself fails, because stream addresses are locked to one IP. Rapid back-to-back requests can get throttled; the script waits and retries.
- **Rate:** the Reddit reader waits about 1.2 seconds between requests. Keep it that way.
- **Jina reader** can serve an old cached copy of a page; its output then says "cached snapshot". Add `-H "X-No-Cache: true"` to the curl to force a live read.
- **Free search engines** (You.com, Exa) have daily limits shared with everyone using them anonymously.

## Rules

- Public, logged-out data only.
- Never use these routes to get past a login, a paywall, or a browser's site blocklist.
- Read at a person's pace. Don't hammer a site.

## When a route breaks

1. Run `python3 health.py` to see which route failed.
2. Load the site's page and find the request its own page now makes for the data: look in the raw HTML for `/api/`, `.json`, `graphql`, `/svc/` or embedded JSON, or in a browser run `performance.getEntriesByType('resource')`. Third-party review widgets (Bazaarvoice, PowerReviews, Yotpo) are often the easiest way in.
3. Patch the one function, rerun `health.py`, and open a pull request.

## License

MIT. See [LICENSE](LICENSE).
