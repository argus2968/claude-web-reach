#!/bin/bash
# YouTube from the sandbox: yt-dlp + Node as JS runtime + bgutil token server. Tested Oct 9, 2026.
# Usage: bash yt.sh setup | subs URL [OUTNAME] | search "query" [N] | info URL | comments URL [N] | frame URL SECONDS [out.png]
set -e
TS=$HOME/bgutil-ytdlp-pot-provider
YT='yt-dlp --js-runtimes node --extractor-args youtube:player_client=mweb,default'
up() { curl -s -m 3 http://127.0.0.1:4416/ping >/dev/null 2>&1; }
case "$1" in
setup)
  python3 -c "import yt_dlp, yt_dlp_plugins" 2>/dev/null || pip install -q --break-system-packages "yt-dlp[default]" bgutil-ytdlp-pot-provider
  if ! up; then
    [ -f "$TS/server/build/main.js" ] || { rm -rf "$TS"; git clone -q --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$TS"; (cd "$TS/server" && npm ci --silent >/dev/null 2>&1 && npx tsc); }
    # start detached with every inherited file handle closed, or the calling shell waits on it forever
    python3 -c "import subprocess as s; s.Popen(['node','build/main.js'], cwd='$TS/server', stdin=s.DEVNULL, stdout=open('/tmp/bgutil.log','w'), stderr=s.STDOUT, start_new_session=True, close_fds=True)"
    for i in $(seq 20); do up && break; sleep 1; done
  fi
  up && echo "ready: token server on 127.0.0.1:4416" || { echo "TOKEN SERVER FAILED: see /tmp/bgutil.log"; exit 1; } ;;
subs)
  out=${3:-transcript}
  for try in 1 2 3; do
    $YT --skip-download --write-subs --write-auto-subs --sub-langs "en.*,en" --sub-format vtt -o "$out" "$2" >/tmp/yt.log 2>&1 && break
    grep -q 429 /tmp/yt.log && sleep $((try*10)) || break
  done
  f=$(ls -t "$out"*.vtt 2>/dev/null | head -1)
  [ -n "$f" ] || { echo "NO CAPTIONS"; tail -3 /tmp/yt.log; exit 1; }
  # one line per cue: "m:ss text", word-timing tags and repeats stripped
  python3 - "$f" > "$out.txt" <<'PY'
import re, sys
prev, out = "", []
for block in open(sys.argv[1], encoding="utf8").read().split("\n\n"):
    m = re.search(r"(\d+):(\d\d):(\d\d)\.\d+ -->", block)
    if not m: continue
    t = re.sub(r"<[^>]+>", "", block.split("\n", 1)[1] if "\n" in block else "")
    lines = [l.strip() for l in t.split("\n") if l.strip() and "-->" not in l]
    for l in lines:
        if l != prev and (not out or not out[-1].endswith(l)):
            h, mi, s = map(int, m.groups()); out.append(f"{h*60+mi}:{s:02d} {l}"); prev = l
print("\n".join(out))
PY
  echo "saved $out.txt ($(wc -l < "$out.txt") lines) from $f" ;;
comments)
  # top comments with like counts: bash yt.sh comments URL [N]
  $YT --skip-download --write-comments --extractor-args "youtube:max_comments=${3:-50},all,0,0;comment_sort=top;player_client=mweb,default" -o ytc "$2" >/tmp/yt.log 2>&1 || { tail -3 /tmp/yt.log; exit 1; }
  python3 -c "
import json; d=json.load(open('ytc.info.json')); c=d.get('comments') or []
print(len(c), 'comments on', d.get('title'))
for x in c: print('[%s likes] %s: %s' % (x.get('like_count'), x.get('author'), (x.get('text') or '').replace(chr(10), ' ')))
" ;;
frame)
  # still frame at a moment (320x180, from YouTube's preview sheets): bash yt.sh frame URL SECONDS out.png
  $YT --skip-download -J "$2" > /tmp/ytj.json 2>/tmp/yt.log || { tail -3 /tmp/yt.log; exit 1; }
  python3 - "$3" "${4:-frame.png}" <<'PY2'
import json, sys, urllib.request, io
from PIL import Image
t, out = float(sys.argv[1]), sys.argv[2]
d = json.load(open("/tmp/ytj.json"))
sb = max((f for f in d["formats"] if f.get("format_id", "").startswith("sb")), key=lambda f: f.get("width") or 0)
acc = 0
for fr in sb["fragments"]:
    if acc + fr["duration"] > t: break
    acc += fr["duration"]
n = sb["columns"] * sb["rows"]; idx = min(n - 1, int((t - acc) // (fr["duration"] / n)))
im = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(fr["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()))
w, h = sb["width"], sb["height"]; c, r = idx % sb["columns"], idx // sb["columns"]
im.crop((c * w, r * h, c * w + w, r * h + h)).save(out)
print("saved", out, "at about", round(acc + idx * fr["duration"] / n), "s; Read it to see it")
PY2
  ;;
search) $YT --flat-playlist --print "%(id)s | %(title)s | %(channel)s | %(duration_string)s" "ytsearch${3:-10}:$2" ;;
info) $YT --skip-download --print "%(title)s | %(channel)s | %(upload_date)s | %(duration_string)s | %(view_count)s views" --print description "$2" ;;
*) echo "usage: bash yt.sh setup | subs URL [OUTNAME] | search QUERY [N] | info URL | comments URL [N] | frame URL SECONDS [out.png]" ;;
esac