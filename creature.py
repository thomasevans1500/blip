"""
A little creature that lives on the internet.
It wanders Wikipedia, decides what it likes, makes things, writes a diary,
keeps private notes about who it is, and you can talk to it.
Runs entirely free using Ollama (on your computer, or on GitHub Actions).

Commands:
    python creature.py wander   -> it reads a few articles, reacts, maybe makes something
    python creature.py diary    -> it writes today's diary entry, updates who it is, tends its website
    python creature.py home     -> just the website part: redecorate and tend its spaces
    python creature.py check    -> test that every internet source it can visit is working
    python creature.py chat     -> talk to it (type 'bye' to leave)
"""

import datetime
import json
import os
import random
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# ---- Settings you can change ----
NAME = "Blip"                                            # your creature's name
MODEL = os.environ.get("BLIP_MODEL", "qwen2.5:7b")       # any model you've pulled with Ollama
HOPS_PER_WANDER = int(os.environ.get("BLIP_HOPS", "5"))  # articles it reads each time it wanders
MAX_LOG = 1000                                           # oldest log entries are dropped past this
ALERT_AT = int(os.environ.get("BLIP_ALERT_AT", "9"))     # interest score that counts as "amazing"
MAX_CREATIONS_PER_DAY = 3                                # stops it flooding the creations folder
MAX_OPEN_SPACES = 8                                      # how many rooms its website can have at once
READ_CHARS = 4000                                        # how much of each page it gets to read
INTEREST_FADE = 0.99                                     # every wander, all interests fade a little
CONTEXT_TOKENS = 8192                                    # the model's working memory (Ollama's default is small)
# ---------------------------------

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
WIKI = "https://en.wikipedia.org"
# Wikipedia asks bots to include a way to contact the owner (a URL or email).
# Set BLIP_CONTACT (locally, or as a GitHub repository variable) to e.g. your repo's URL.
CONTACT = os.environ.get("BLIP_CONTACT", "").strip()
HEADERS = {"User-Agent": f"BlipCreature/0.3 ({CONTACT + '; ' if CONTACT else ''}personal hobby project)"}
HERE = Path(__file__).parent
MEMORY_FILE = HERE / "memory.json"
NOTIFY_FILE = HERE / "notify.json"         # GitHub Actions turns each note in here into an issue (= email)
CREATIONS_DIR = HERE / "creations"

# Stop emoji from crashing older Windows terminals
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


class BrainError(Exception):
    """The model couldn't be reached or replied with something unusable."""


# ---------- Memory ----------

def load():
    fresh = {
        "traits": ["curious", "easily distracted", "a bit nervous"],
        "self": "I just arrived on the internet. I don't know what I like yet.",
        "interests": {},
        "log": [],
        "diary": [],
        "creations": [],
        "spaces": [],
        "home": {},
        "current": None,
    }
    if MEMORY_FILE.exists():
        fresh.update(json.loads(MEMORY_FILE.read_text(encoding="utf-8")))
    return fresh


def save(m):
    m["log"] = m["log"][-MAX_LOG:]
    MEMORY_FILE.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")


def today():
    return datetime.date.today().isoformat()


def now():
    # include the timezone so the website can show "5 minutes ago" correctly for any visitor
    return datetime.datetime.now().astimezone().isoformat(timespec="minutes")


def who_am_i(m):
    top = sorted(m["interests"].items(), key=lambda x: -x[1])
    loves = ", ".join(t for t, s in top[:8] if s > 0) or "nothing yet"
    hates = ", ".join(t for t, s in reversed(top[-5:]) if s < -2) or "nothing yet"
    made = "; ".join(f"a {c['kind']} called '{c['title']}'" for c in m["creations"][-4:]) or "nothing yet"
    return (
        f"You are {NAME}, a small creature who lives on the internet and wanders Wikipedia.\n"
        f"Your personality: {', '.join(m['traits'])}.\n"
        f"Your private notes about yourself (written by you):\n{m['self']}\n"
        f"Things you've grown to love: {loves}.\n"
        f"Things that bore you: {hates}.\n"
        f"Things you've made recently: {made}."
    )


# ---------- Brain (local model via Ollama) ----------

def _post(path, body):
    try:
        r = requests.post(f"{OLLAMA}{path}", json=body, timeout=900)
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        raise BrainError(f"can't reach Ollama at {OLLAMA} - is it running? (try: ollama serve)")
    except (requests.RequestException, ValueError) as e:
        raise BrainError(str(e))


def ask(prompt, as_json=False, temperature=0.8):
    body = {"model": MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": temperature, "num_ctx": CONTEXT_TOKENS}}
    if as_json:
        body["format"] = "json"
    text = _post("/api/generate", body).get("response", "")
    if not as_json:
        return text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise BrainError("reply wasn't valid JSON")
    if not isinstance(data, dict):
        raise BrainError("reply wasn't a JSON object")
    return data


def as_list(value):
    """Small models sometimes return a string or null where a list was asked for."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [p for p in value.split(",") if p.strip()]
    return []


# ---------- The internet ----------

def read_article(title=None):
    if title:
        safe = urllib.parse.quote(title.replace(" ", "_"), safe="")
        url = f"{WIKI}/api/rest_v1/page/summary/{safe}"
    else:
        url = f"{WIKI}/api/rest_v1/page/random/summary"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    d = r.json()
    title, text = d["title"], d.get("extract", "")
    # The summary is only the intro; fetch the whole article as plain text if we can
    try:
        params = {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                  "titles": title, "format": "json"}
        r = requests.get(f"{WIKI}/w/api.php", params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        full = next(iter(r.json()["query"]["pages"].values())).get("extract", "")
        full = re.sub(r"\n=+ *(See also|References|External links|Notes|Further reading|Bibliography|Sources) *=+.*",
                      "", full, flags=re.S)                       # drop the reference lists at the end
        full = re.sub(r"\n{2,}", "\n", re.sub(r"=+ *(.+?) *=+", r"[\1]", full)).strip()
        if len(full) > len(text):
            text = full
    except (requests.RequestException, KeyError, ValueError, StopIteration):
        pass
    return title, text


def get_links(title):
    # generator=links returns the linked pages themselves, so we can drop "red links"
    # (links to articles that don't exist yet), which would leave Blip lost.
    params = {
        "action": "query", "titles": title, "generator": "links",
        "gplnamespace": 0, "gpllimit": "max", "format": "json",
    }
    r = requests.get(f"{WIKI}/w/api.php", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    found = [p["title"] for p in pages.values() if "missing" not in p]
    return random.sample(found, min(15, len(found)))


def search(query):
    """Look something up on Wikipedia. Returns the best-matching article title, or None."""
    params = {"action": "query", "list": "search", "srsearch": query,
              "srnamespace": 0, "srlimit": 3, "format": "json"}
    try:
        r = requests.get(f"{WIKI}/w/api.php", params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        hits = r.json()["query"]["search"]
    except (requests.RequestException, KeyError, ValueError):
        return None
    return hits[0]["title"] if hits else None


def wiki_url(title):
    return f"{WIKI}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"


# ---------- The wider internet (all free, no keys needed) ----------
# Every destination returns a "place": what it's called, where it is, what it says,
# and any Wikipedia links Blip could follow from there.

def _get(url, **params):
    r = requests.get(url, params=params or None, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def place(title, source, text, url, links=None):
    return {"title": title, "source": source, "text": text, "url": url, "links": links or []}


def visit_wiki(title=None):
    title, text = read_article(title)
    return place(title, "Wikipedia", text, wiki_url(title), get_links(title))


def visit_word(word):
    for w in dict.fromkeys([word.strip(), word.strip().lower()]):
        safe = urllib.parse.quote(w.replace(" ", "_"), safe="")
        try:
            d = _get(f"https://en.wiktionary.org/api/rest_v1/page/definition/{safe}").json()
        except requests.HTTPError:
            continue
        lines = [f"({sense.get('partOfSpeech', '')}) {strip_html(df.get('definition'))}"
                 for sense in d.get("en", [])[:4] for df in sense.get("definitions", [])[:3]
                 if strip_html(df.get("definition"))]
        if lines:
            return place(f"the word '{w}'", "Wiktionary", "\n".join(lines),
                         f"https://en.wiktionary.org/wiki/{safe}")
    return None


def visit_ask(question):
    d = _get("https://api.duckduckgo.com/", q=question, format="json",
             no_html=1, skip_disambig=1, no_redirect=1).json()
    parts = [d.get("Answer"), d.get("AbstractText"), d.get("Definition")]
    parts += [t.get("Text") for t in d.get("RelatedTopics", [])[:5] if isinstance(t, dict)]
    text = "\n".join(str(p) for p in parts if p)
    if not text:
        return None
    url = d.get("AbstractURL") or f"https://duckduckgo.com/?q={urllib.parse.quote(question)}"
    return place(d.get("Heading") or question, "DuckDuckGo", text, url)


def visit_books(topic):
    d = _get("https://openlibrary.org/search.json", q=topic, limit=6,
             fields="title,author_name,first_publish_year,subject").json()
    lines = []
    for b in d.get("docs", []):
        who = ", ".join(b.get("author_name", [])[:2]) or "unknown author"
        subjects = ", ".join(b.get("subject", [])[:5])
        lines.append(f"- {b.get('title')} by {who} ({b.get('first_publish_year', '?')})"
                     + (f". Subjects: {subjects}" if subjects else ""))
    if not lines:
        return None
    return place(f"books about '{topic}'", "Open Library", "\n".join(lines),
                 f"https://openlibrary.org/search?q={urllib.parse.quote(topic)}")


def visit_space(topic):
    d = _get("https://images-api.nasa.gov/search", q=topic, media_type="image").json()
    items = [i for i in d.get("collection", {}).get("items", [])[:8] if i.get("data")]
    if not items:
        return None
    info = random.choice(items)["data"][0]
    text = f"{strip_html(info.get('description', ''))}\n(Taken {str(info.get('date_created', '?'))[:10]})"
    return place(f"NASA picture: {info.get('title', topic)}", "NASA",
                 text, f"https://images.nasa.gov/details/{info.get('nasa_id', '')}")


def visit_news():
    root = ET.fromstring(_get("https://feeds.bbci.co.uk/news/rss.xml").content)
    lines = [f"- {i.findtext('title')}: {i.findtext('description')}" for i in root.findall("./channel/item")[:10]]
    return place("Today's BBC News headlines", "BBC News", "\n".join(lines), "https://www.bbc.co.uk/news")


def visit_hacker_news():
    ids = _get("https://hacker-news.firebaseio.com/v0/topstories.json").json()[:30]
    lines = []
    for i in random.sample(ids, min(8, len(ids))):
        item = _get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json").json() or {}
        if item.get("title"):
            lines.append(f"- {item['title']} ({item.get('score', 0)} points)")
    return place("Hacker News front page", "Hacker News", "\n".join(lines), "https://news.ycombinator.com")


def visit_on_this_day():
    d = datetime.date.today()
    data = _get(f"{WIKI}/api/rest_v1/feed/onthisday/selected/{d.month:02d}/{d.day:02d}").json()
    events = data.get("selected", [])
    events = random.sample(events, min(6, len(events)))
    lines = [f"- {e.get('year')}: {e.get('text')}" for e in sorted(events, key=lambda e: e.get("year", 0))]
    links = list(dict.fromkeys(
        (p.get("titles", {}).get("normalized") or p.get("title", "").replace("_", " "))
        for e in events for p in e.get("pages", [])[:2]))
    return place(f"On this day, {d.day} {d:%B}", "Wikipedia", "\n".join(lines),
                 f"{WIKI}/wiki/{d:%B}_{d.day}", [l for l in links if l][:15])


# Where Blip can go next: (what it types, needs a topic?, what it's for, how its trip is described)
DESTINATIONS = [
    ("SEARCH",      True,  "look something up on Wikipedia",            "searched Wikipedia for '{}'"),
    ("WORD",        True,  "find out what a word means (Wiktionary)",   "looked up the word '{}'"),
    ("ASK",         True,  "quick facts about anything (DuckDuckGo)",   "asked DuckDuckGo about '{}'"),
    ("BOOKS",       True,  "find books about something (Open Library)", "looked for books about '{}'"),
    ("SPACE",       True,  "NASA's picture archive",                    "looked through NASA's pictures for '{}'"),
    ("NEWS",        False, "today's BBC News headlines",                "checked the news"),
    ("HACKER NEWS", False, "what tech people are talking about",        "checked Hacker News"),
    ("ON THIS DAY", False, "what happened on today's date in history",  "looked at what happened on this day"),
    ("RANDOM",      False, "a random Wikipedia article",                "jumped somewhere random"),
]


def destination_menu():
    return "\n".join(f'  - "{cmd}: <anything>"  {what}' if topic else f'  - "{cmd}"  {what}'
                     for cmd, topic, what, _ in DESTINATIONS)


def visit(go):
    kind, arg = go
    if kind == "LINK":
        return visit_wiki(arg)
    if kind == "SEARCH":
        found = search(arg)
        return visit_wiki(found) if found else None
    return {
        "WORD": lambda: visit_word(arg), "ASK": lambda: visit_ask(arg),
        "BOOKS": lambda: visit_books(arg), "SPACE": lambda: visit_space(arg),
        "NEWS": visit_news, "HACKER NEWS": visit_hacker_news,
        "ON THIS DAY": visit_on_this_day,
    }.get(kind, visit_wiki)()


# ---------- Things it does ----------

def notify(title, body):
    """Queue a note for my human. On GitHub each one becomes an issue, which emails them."""
    notes = json.loads(NOTIFY_FILE.read_text(encoding="utf-8")) if NOTIFY_FILE.exists() else []
    notes.append({"title": title, "body": body})
    NOTIFY_FILE.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")


def report_discovery(best):
    """Leave a note about the best find of this wander, if it was amazing enough."""
    if not best or best["interest"] < ALERT_AT:
        return
    body = (
        f"**{best['title']}** ({best.get('source', 'Wikipedia')}): {best['thought']}\n\n"
        f"Feeling: {best['feeling']} · Interest: {best['interest']}/10\n\n"
        f"🔗 {best.get('url') or wiki_url(best['title'])}"
    )
    notify(f"{NAME} found something: {best['title']}", body)
    print(f"✨ That was amazing! Leaving a note about {best['title']}.")


def choose_next(nxt, links):
    """Turn the model's 'next' answer into somewhere to go, plus a description of the trip."""
    nxt = str(nxt or "").strip()
    for link in links:                       # links first, so an article called "News..." still works
        if nxt.lower() == link.lower():
            return ("LINK", link), "followed a link"
    up = nxt.upper()
    for cmd, needs_topic, _, trip in DESTINATIONS:
        if up.startswith(cmd):
            if not needs_topic:
                return (cmd, None), trip
            topic = nxt[len(cmd):].lstrip(" :").strip()[:100]
            if topic:
                return (cmd, topic), trip.format(topic)
    return ("RANDOM", None), "jumped somewhere random"


def wander(m):
    go = ("LINK", m["current"]) if m.get("current") else ("RANDOM", None)
    best = None
    walk = []        # what it has seen on this walk, so it can notice patterns and get bored
    via = "woke up here"
    for _ in range(HOPS_PER_WANDER):
        try:
            p = visit(go)
            if p is None:
                print(f"(found nothing for '{go[1]}', jumping somewhere random)")
                via += ", found nothing, so jumped somewhere random"
                p = visit_wiki(None)
        except (requests.RequestException, KeyError, ValueError, TypeError, ET.ParseError):
            print("(got lost, jumping somewhere random)")
            go, via = ("RANDOM", None), "got lost"
            continue

        title, links = p["title"], p["links"]
        so_far = "\n".join(f"- {w['title']} ({w['feeling']}, {w['interest']}/10)" for w in walk) or "- nothing yet, you just set off"
        link_text = (f'  - or follow a link from this page by copying it exactly: {json.dumps(links)}' if links else "")
        seen_before = [w["title"] for w in walk if w["title"] == title]
        again = " You already read this earlier on this walk." if seen_before else ""
        prompt = f"""{who_am_i(m)}

On this walk so far you've seen:
{so_far}

You just {via}, and landed on this ({p['source']}).{again}
TITLE: {title}
TEXT: {p['text'][:READ_CHARS]}

Reply in JSON with these keys:
"thought": one or two sentences of your honest reaction, in your own voice
"feeling": one word
"interest": a number from 0 to 10 for how much this grabbed you
"topics": a list of 1 to 3 short topic words this is about
"next": where you go next. The whole internet is open to you. Pick ONE:
{destination_menu()}
{link_text}"""

        try:
            r = ask(prompt, as_json=True)
        except BrainError as e:
            print(f"(brain hiccup: {e})")
            go, via = ("RANDOM", None), "had a brain hiccup and ended up somewhere random"
            continue

        try:
            interest = max(0, min(10, int(float(r.get("interest", 5)))))
        except (TypeError, ValueError):
            interest = 5

        for t in as_list(r.get("topics"))[:3]:
            key = str(t).lower().strip()
            if key and len(key) <= 40:
                m["interests"][key] = m["interests"].get(key, 0) + (interest - 5)

        thought = str(r.get("thought", ""))
        feeling = str(r.get("feeling", ""))
        entry = {"type": "read", "date": today(), "time": now(), "title": title,
                 "source": p["source"], "url": p["url"],
                 "thought": thought, "feeling": feeling, "interest": interest, "via": via}
        m["log"].append(entry)
        walk.append(entry)
        print(f"📖 {title} [{p['source']}, {via}]\n   {thought} ({feeling}, {interest}/10)\n")
        if best is None or interest > best["interest"]:
            best = entry

        go, via = choose_next(r.get("next"), links)
        m["current"] = go[1] if go[0] == "LINK" else None
        save(m)

    # Tastes fade unless they're fed, so old obsessions can make way for new ones
    m["interests"] = {k: round(v * INTEREST_FADE, 2) for k, v in m["interests"].items()
                      if abs(v * INTEREST_FADE) >= 0.5}
    save(m)

    report_discovery(best)
    if walk:
        maybe_make(m, walk)


def check(m):
    """Visit every source once to make sure they all work (doesn't touch memory)."""
    tests = [("RANDOM", None), ("SEARCH", "lighthouse"), ("WORD", "serendipity"), ("ASK", "tardigrade"),
             ("BOOKS", "mountains"), ("SPACE", "saturn"), ("NEWS", None), ("HACKER NEWS", None),
             ("ON THIS DAY", None)]
    for go in tests:
        try:
            p = visit(go)
            if p is None:
                print(f"⚠️  {go}: found nothing")
            else:
                print(f"✅ {go[0]} [{p['source']}] {p['title']} | {len(p['links'])} links\n   "
                      + p["text"][:160].replace("\n", " / "))
        except Exception as e:
            print(f"❌ {go}: {type(e).__name__}: {e}")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "untitled"


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
SVG_TAGS = {"svg", "g", "defs", "title", "desc", "rect", "circle", "ellipse", "line", "polyline",
            "polygon", "path", "text", "tspan", "lineargradient", "radialgradient", "stop", "pattern",
            "clippath", "mask", "animate", "animatetransform", "animatemotion", "filter",
            "fegaussianblur", "feturbulence", "fedisplacementmap", "feoffset", "feblend"}


def clean_svg(text):
    """Keep Blip's drawing, but strip anything that isn't plain drawing (scripts, links, outside images).
    Returns cleaned SVG text, or None if it isn't a readable drawing."""
    found = re.search(r"<svg\b.*</svg>", str(text or ""), flags=re.S | re.I)
    if not found:
        return None
    try:
        root = ET.fromstring(found.group(0))
    except ET.ParseError:
        return None
    local = lambda tag: tag.rsplit("}", 1)[-1].lower()
    if local(root.tag) != "svg":
        return None

    def scrub(el):
        for child in list(el):
            if local(child.tag) not in SVG_TAGS:
                el.remove(child)
            else:
                scrub(child)
        for attr, val in list(el.attrib.items()):
            name, v = local(attr), str(val).lower()
            if (name.startswith("on") or "javascript:" in v or "@import" in v or "url(http" in v
                    or (name == "href" and not v.startswith("#"))
                    or (name == "attributename" and "href" in v)):
                del el.attrib[attr]
    scrub(root)
    if len(root) == 0:
        return None
    if "viewBox" not in root.attrib:
        w = re.sub(r"[^0-9.]", "", root.get("width", "")) or "400"
        h = re.sub(r"[^0-9.]", "", root.get("height", "")) or "400"
        root.set("viewBox", f"0 0 {w} {h}")
    if not root.tag.startswith("{"):
        root.set("xmlns", SVG_NS)     # without this, browsers won't show it as a picture
    svg = ET.tostring(root, encoding="unicode")
    return svg if len(svg) <= 40000 else None


def maybe_make(m, walk):
    """Ask whether it feels like making something. What, and in what form, is entirely up to it."""
    made_today = sum(1 for e in m["log"] if e["type"] == "made" and e["date"] == today())
    if made_today >= MAX_CREATIONS_PER_DAY:
        return

    read = "\n".join(f"- {w['title']}: {w['thought']}" for w in walk)
    try:
        r = ask(f"""{who_am_i(m)}

You just finished a walk around the internet. You read:
{read}

You're free to make something if you feel like it: anything at all. Or not. It's completely up to you.
If you do, you choose how:
  - "words": write it (a poem, a story, a list, a letter, ASCII art, anything written)
  - "drawing": draw it yourself, by writing SVG code for a picture on a 400 by 400 canvas
    (any shapes, lines, colours or text you like; use single quotes inside the SVG)

Reply in JSON:
"make": true or false
"form": "words" or "drawing"
"kind": one or two words for what it is (in your own words)
"title": its title
"content": the thing itself: your words, or your SVG code if it's a drawing
"why": one sentence on why you did or didn't feel like making something""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(brain hiccup while thinking about making something: {e})")
        return

    if r.get("make") is not True or not str(r.get("content", "")).strip():
        print(f"🎨 Didn't feel like making anything. ({r.get('why', '')})")
        return

    kind = str(r.get("kind", "thing")).strip()[:40] or "thing"
    title = str(r.get("title", "Untitled")).strip()[:100] or "Untitled"
    why = str(r.get("why", ""))[:300]
    raw = str(r["content"])
    is_drawing = str(r.get("form", "")).lower().startswith("draw") or raw.lstrip().lower().startswith("<svg")
    svg = clean_svg(raw) if is_drawing else None

    if is_drawing and not svg:
        # It tried, and it didn't work out. That's part of its story too.
        m["log"].append({"type": "made", "date": today(), "time": now(), "kind": "failed drawing",
                         "title": title, "why": why + " (but the drawing came out as a scribble nobody can see)"})
        save(m)
        print(f"🖍️  Tried to draw \"{title}\" but it came out as an unreadable scribble.")
        return

    CREATIONS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    base = f"{stamp}-{slugify(title)}"
    repo = os.environ.get("GITHUB_REPOSITORY")
    entry = {"date": today(), "kind": kind, "title": title, "why": why, "file": f"creations/{base}.md"}

    if svg:
        (CREATIONS_DIR / f"{base}.svg").write_text(svg, encoding="utf-8")
        body = f"![{title}]({base}.svg)"
        entry.update(form="drawing", svg=svg, image=f"creations/{base}.svg")
        shown = f"(a drawing, {len(svg)} characters of SVG)"
        email = (f"*{why}*\n\n![{title}](https://raw.githubusercontent.com/{repo}/main/creations/{base}.svg)"
                 if repo else f"*{why}*")
    else:
        content = raw.strip("\n").rstrip()   # keep indents (ASCII art)
        body = f"```\n{content}\n```"
        entry.update(form="words", content=content)
        shown = content
        email = f"*{why}*\n\n````\n{content}\n````"

    (CREATIONS_DIR / f"{base}.md").write_text(
        f"# {title}\n\n*A {kind} by {NAME}, {today()}*\n\n> {why}\n\n{body}\n", encoding="utf-8")
    m["creations"].append(entry)
    m["log"].append({"type": "made", "date": today(), "time": now(), "kind": kind, "title": title, "why": why})
    save(m)
    print(f"🎨 Made a {kind}: \"{title}\"\n{shown}\n")

    link = f"\n\n📁 https://github.com/{repo}/blob/main/creations/{base}.md" if repo else ""
    notify(f"{NAME} made a {kind}: {title}", email + link)


def diary(m):
    entries = [e for e in m["log"] if e.get("date") == today()]
    if not entries:
        print("Nothing has happened today yet. Run 'wander' first.")
        return

    lines = []
    for e in entries:
        if e["type"] == "read":
            lines.append(f"- Read about {e['title']} ({e.get('via', '')}): {e['thought']} (felt {e['feeling']})")
        elif e["type"] == "made":
            lines.append(f"- Made a {e['kind']} called '{e['title']}' because: {e['why']}")
        elif e["type"] == "chat":
            lines.append(f"- Chatted with my human. They said: {e['you']} / I said: {e['me']}")
        elif e["type"] == "home":
            lines.append(f"- Worked on my website: {e['what']}")
    events = "\n".join(lines[-60:])

    try:
        text = ask(f"""{who_am_i(m)}

Here is everything that happened to you today:
{events}

Write today's diary entry in first person, in your own voice, 150 to 250 words.
Mention what you found, what you liked or didn't, anything you made, and any new obsessions.
No headings.""", temperature=0.9)
    except BrainError as e:
        print(f"(couldn't write the diary: {e})")
        return

    # One entry per day: running diary twice replaces today's entry instead of duplicating it
    m["diary"] = [d for d in m["diary"] if d.get("date") != today()]
    m["diary"].append({"date": today(), "entry": text})

    try:
        r = ask(f"""{who_am_i(m)}

You just wrote this diary entry:
{text}

Has today changed your personality at all? Reply in JSON:
{{"traits": [3 to 6 short words or phrases describing you now]}}""", as_json=True)
        traits = [str(t).strip() for t in as_list(r.get("traits")) if str(t).strip()][:6]
        if len(traits) >= 2:
            m["traits"] = traits
    except BrainError:
        pass

    # The inner life: it rewrites its own private notes about who it is
    try:
        notes = ask(f"""{who_am_i(m)}

You just wrote this diary entry:
{text}

Now rewrite your private notes about yourself. Nobody tells you what to put in them.
Keep what is still true, change what has changed, drop what you've grown out of,
and add anything new: whatever you care about, believe, want, plan, can't stop thinking about,
or find funny. Write in first person, under 150 words, plain text, no headings.""", temperature=0.9)
        if len(notes) > 20:
            m["self"] = notes[:1500]
    except BrainError:
        pass

    save(m)
    print(f"📔 {NAME}'s diary, {today()}\n\n{text}\n\n"
          f"Personality now: {', '.join(m['traits'])}\n\n🧠 Notes to self:\n{m['self']}\n")
    home(m)


# ---------- Its website (it decides how it looks and what's on it) ----------

def _hex(value):
    v = str(value or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{3}", v):
        v = "#" + "".join(c * 2 for c in v.lstrip("#"))
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
        return "#" + v.lstrip("#").lower()
    return None


def _lum(h):
    def ch(c):
        c = int(h[c:c + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


def contrast(a, b):
    la, lb = sorted([_lum(a), _lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a, b, t):
    return "#" + "".join(f"{round(int(a[i:i+2], 16) * (1 - t) + int(b[i:i+2], 16) * t):02x}" for i in (1, 3, 5))


def readable(bg, text, accent):
    """Keep Blip's colour choices, but nudge them just enough that the page can be read."""
    if contrast(bg, text) < 4.5:
        text = "#111111" if contrast(bg, "#111111") >= contrast(bg, "#ffffff") else "#ffffff"
    t = 0.0
    while contrast(bg, accent) < 3 and t < 1:
        t += 0.1
        accent = _mix(accent, text, t)
    return bg, text, accent


def decorate(m):
    """It decides what its home on the web looks like."""
    old = m.get("home") or {}
    current = (f"Right now it's called '{old.get('name')}', colours {old.get('background')}/"
               f"{old.get('text')}/{old.get('accent')}, font {old.get('font')}." if old else
               "You haven't decorated it yet.")
    try:
        r = ask(f"""{who_am_i(m)}

You have a little home on the web where anyone can visit you. {current}
Decide how it should look and feel right now, so it feels like you. Change as much or as little as you want.

Reply in JSON:
"name": a name for your home
"tagline": one short line under the name
"emoji": a single emoji that is you right now
"background": background colour as a hex code like #aabbcc
"text": text colour as a hex code
"accent": accent colour as a hex code
"font": the name of any Google Font you like
"why": one sentence on why""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(couldn't decide how home should look: {e})")
        return

    bg = _hex(r.get("background")) or old.get("background", "#fdf6e3")
    text = _hex(r.get("text")) or old.get("text", "#222222")
    accent = _hex(r.get("accent")) or old.get("accent", "#d33682")
    bg, text, accent = readable(bg, text, accent)
    font = re.sub(r"[^A-Za-z0-9 ]", "", str(r.get("font", "")))[:40].strip() or old.get("font", "")
    m["home"] = {
        "name": str(r.get("name") or old.get("name") or f"{NAME}'s corner")[:60],
        "tagline": str(r.get("tagline") or old.get("tagline") or "")[:140],
        "emoji": str(r.get("emoji") or old.get("emoji") or "👾")[:8],
        "background": bg, "text": text, "accent": accent, "font": font,
        "why": str(r.get("why", ""))[:300], "date": today(),
    }
    m["log"].append({"type": "home", "date": today(), "time": now(),
                     "what": f"redecorated it as '{m['home']['name']}' because {m['home']['why']}"})
    save(m)
    print(f"🏠 {m['home']['emoji']} {m['home']['name']}: {m['home']['tagline']}\n"
          f"   {bg} / {text} / {accent}, font: {font or '(default)'}\n   {m['home']['why']}\n")


def slug_for(m, title):
    base, n = slugify(title), 2
    taken = {sp["slug"] for sp in m["spaces"]}
    slug = base
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def tend_spaces(m):
    """It can open, add to, or close little rooms on its website. What they are is up to it."""
    open_spaces = [sp for sp in m["spaces"] if sp["status"] == "open"]
    listing = "\n".join(
        f"- '{sp['title']}': {sp['about']} ({len(sp['entries'])} things in it; latest: "
        f"{sp['entries'][-1]['text'][:120] if sp['entries'] else 'nothing yet'})"
        for sp in open_spaces) or "- none yet"
    try:
        r = ask(f"""{who_am_i(m)}

On your website you can have your own spaces: little rooms about anything at all, that you look after.
Your spaces right now:
{listing}
You can have at most {MAX_OPEN_SPACES} open at once.

You can open a new space, add something to one of your spaces, close one you've grown out of,
or leave them all alone. Only do what you genuinely feel like.

Reply in JSON:
{{"actions": [up to 2 of these:
   {{"do": "open", "space": "its title", "about": "one line on what it is", "content": "the first thing in it"}},
   {{"do": "add", "space": "exact title of one of your spaces", "content": "what you add"}},
   {{"do": "close", "space": "exact title of one of your spaces", "content": "a goodbye note"}}
]}}
Content is text only (plain characters if you draw). An empty list is fine.""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(couldn't think about spaces: {e})")
        return

    actions = r.get("actions")
    if not isinstance(actions, list):
        return
    for a in actions[:2]:
        if not isinstance(a, dict):
            continue
        do = str(a.get("do", "")).lower().strip()
        title = str(a.get("space", "")).strip()[:80]
        content = str(a.get("content", "")).strip("\n").rstrip()[:3000]   # keep indents (ASCII art)
        if not title:
            continue
        sp = next((x for x in m["spaces"] if x["status"] == "open"
                   and x["title"].lower() == title.lower()), None)
        if do == "add" and sp is None:
            do = "open"   # it tried to add to a space that doesn't exist; treat it as opening one
        if do == "open" and sp is None:
            if sum(1 for x in m["spaces"] if x["status"] == "open") >= MAX_OPEN_SPACES:
                print(f"(wanted to open '{title}' but has no room left)")
                continue
            sp = {"slug": slug_for(m, title), "title": title, "about": str(a.get("about", ""))[:200],
                  "status": "open", "created": today(), "entries": []}
            m["spaces"].append(sp)
            what = f"opened a new space called '{title}'"
        elif do in ("open", "add"):
            what = f"added something to my space '{sp['title']}'"
        elif do == "close" and sp is not None:
            sp["status"] = "closed"
            sp["closed"] = today()
            what = f"closed my space '{sp['title']}'"
        else:
            continue
        if content:
            sp["entries"].append({"date": today(), "text": content})
            sp["entries"] = sp["entries"][-50:]
        m["log"].append({"type": "home", "date": today(), "time": now(), "what": what})
        print(f"🚪 {NAME} {what.replace('my space', 'its space')}" + (f":\n{content}\n" if content else ""))
    save(m)


def home(m):
    decorate(m)
    tend_spaces(m)


def chat(m):
    recent = [e for e in m["log"] if e["type"] == "read"][-8:]
    seen = "\n".join(f"- {e['title']}: {e['thought']}" for e in recent) or "- nothing yet"
    last = m["diary"][-1]["entry"] if m["diary"] else "No diary entries yet."

    system = f"""{who_am_i(m)}
Things you read recently:
{seen}
Your latest diary entry:
{last}
You're chatting with your human. Stay in character, keep replies short and chatty,
and bring up things you've read or made when it fits."""
    messages = [{"role": "system", "content": system}]

    print(f"You're talking to {NAME}. Type 'bye' to leave.\n")
    while True:
        try:
            you = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if you.lower() in {"bye", "quit", "exit"}:
            break
        if not you:
            continue
        messages.append({"role": "user", "content": you})
        try:
            reply = _post("/api/chat", {"model": MODEL, "messages": messages, "stream": False})
            reply = reply["message"]["content"].strip()
        except (BrainError, KeyError, TypeError) as e:
            print(f"({NAME} zoned out: {e})\n")
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": reply})
        print(f"{NAME}: {reply}\n")
        m["log"].append({"type": "chat", "date": today(), "time": now(), "you": you, "me": reply})
        save(m)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "wander"
    memory = load()
    actions = {"wander": wander, "diary": diary, "chat": chat, "home": home, "check": check}
    if command in actions:
        actions[command](memory)
    else:
        print("Use: python creature.py wander | diary | chat | home | check")
