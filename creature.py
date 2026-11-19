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
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# ---- Settings you can change ----
NAME = "Blip"                                            # your creature's name
MODEL = os.environ.get("BLIP_MODEL", "gemma3:4b")       # any model you've pulled with Ollama
HOPS_PER_WANDER = int(os.environ.get("BLIP_HOPS", "7"))  # most pages a walk can take (a vivid, energetic Blip)
MAX_LOG = 1000                                           # oldest log entries are dropped past this
ALERT_AT = int(os.environ.get("BLIP_ALERT_AT", "9"))     # interest score that counts as "amazing"
MAX_CREATIONS_PER_DAY = 3                                # stops it flooding the creations folder
MAX_ACTIVE_PROJECTS = 3                                  # projects it can have on the go at once
MAX_MAIL_PER_HOUR = 3                                    # messages from its human it answers per hour
MAX_LETTERS_PER_DAY = 2                                  # emails it can write to its human per day
MAX_THOUGHTS = 200                                       # thinking-out-loud entries kept
MAX_OPINIONS = 100                                       # opinions kept (least recently formed drop off)
PORTRAIT_EVERY_DAYS = 7                                  # how often it's offered the chance to redraw itself
SHORT_ROOM, LONG_ROOM, FADED_ROOM = 40, 40, 200          # how much fits in each part of its memory
MAX_DARLINGS = 8                                         # things he can be fond of at once
MAIL_FRESH_HOURS = 3                                     # how long a message from his human stays front of mind
NAP_EVERY_HOURS = 4                                      # it naps (consolidates memory, grows its sheet)
MAX_ADDED_PER_SECTION = 6                                # lines it can add to each part of its character sheet
MAX_SCRAPBOOK = 300                                      # memories it can keep (oldest drop off past this)
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
FIRST_LIVES_FILE = HERE / "past_lives.json"  # identities Blip has moved on from (fresh starts), kept as history
FRESH_START = "2026-11-19-playful"          # change this to give Blip a new fresh start (archives the old self)
CHARACTER_FILE = HERE / "character.md"     # who Blip is, written by a person; Blip adds to it in naps
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
        "scrapbook": [],
        "thoughts": [],
        "projects": [],
        "mail": [],
        "opinions": {},
        "about": "",
        "portrait": None,
        "mood": {},
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


WORD_RE = re.compile(r"[a-z]{4,}")


# ---------- Character sheet (a person wrote who he is; he adds to it) ----------

def read_character():
    """Parse character.md: '## Section' headings with '- line' bullets. Comments are ignored."""
    if not CHARACTER_FILE.exists():
        return {}
    text = re.sub(r"<!--.*?-->", "", CHARACTER_FILE.read_text(encoding="utf-8"), flags=re.S)
    sections, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current and line.strip().startswith("- "):
            sections[current].append(line.strip()[2:].strip())
    return sections


def sheet_text(m):
    written, added = read_character(), m.get("sheet", {})
    out = []
    for sec in list(written) + [x for x in added if x not in written]:
        out.append(f"{sec}:")
        out += [f"- {line}" for line in written.get(sec, [])]
        out += [f"- {x['text']} (you added this yourself)" for x in added.get(sec, [])]
    return "\n".join(out)


# ---------- Memory: small on purpose; things have to earn their place ----------
# short term: what happened lately; fades within days unless it keeps coming back to mind.
# long term: kept for good; things that came back on different days, or big moments. Limited room:
#   a newcomer must be stronger than the weakest thing there, which then fades.
# faded: a one-sentence trace of what was pushed out of long term.

def memory_store(m):
    mem = m.setdefault("memory", {"short": [], "long": [], "faded": []})
    if "scrapbook" in m and not m.get("scrapbook_moved"):
        for x in m["scrapbook"]:               # old scrapbook memories were kept on purpose: long term
            mem["long"].append(_memory_item(x["memory"], 1.0, "scrapbook", x.get("date")))
        mem["long"] = mem["long"][-LONG_ROOM:]
        m["scrapbook_moved"] = True
    return mem


def _memory_item(text, strength, source, born=None):
    return {"id": f"{datetime.datetime.now():%Y%m%d%H%M%S}{random.randint(100, 999)}", "text": str(text)[:600],
            "born": born or today(), "strength": round(strength, 3), "recalls": 0, "days": [], "source": source}


def _fade(m, item):
    first = re.split(r"(?<=[.!?])\s", item["text"].strip())[0][:180]
    mem = memory_store(m)
    mem["faded"] = (mem["faded"] + [{"text": first, "from": item["born"], "faded": today()}])[-FADED_ROOM:]


def _admit_long(m, item):
    mem = memory_store(m)
    if len(mem["long"]) < LONG_ROOM:
        mem["long"].append(item)
        return True
    weakest = min(mem["long"], key=lambda x: x["strength"])
    if item["strength"] <= weakest["strength"]:
        return False                           # not worth more than anything already there
    mem["long"].remove(weakest)
    _fade(m, weakest)
    mem["long"].append(item)
    return True


def remember(m, text, strength=0.5, big=False, source=""):
    """Something happened worth remembering. Big moments go straight to long term (if they're strong enough)."""
    text = str(text).strip()
    if len(text) < 8:
        return
    mem = memory_store(m)
    item = _memory_item(text, max(strength, 1.0) if big else strength, source)
    if big and _admit_long(m, item):
        return
    mem["short"].append(item)
    if len(mem["short"]) > SHORT_ROOM:
        weakest = min(mem["short"], key=lambda x: x["strength"])
        mem["short"].remove(weakest)
        if weakest["recalls"]:
            _fade(m, weakest)


def recall(m, context="", n=5):
    """What comes to mind: memories related to what it's looking at, the latest, and one from long ago.
    Coming back to mind makes a memory stronger (once per hour)."""
    mem = memory_store(m)
    pool = mem["long"] + mem["short"]
    if not pool:
        return []
    words = set(WORD_RE.findall(context.lower()))
    related = sorted(pool, key=lambda x: -len(words & set(WORD_RE.findall(x["text"].lower()))))
    picks = [x for x in related if len(words & set(WORD_RE.findall(x["text"].lower()))) >= 2][:n - 3]
    picks += [x for x in reversed(mem["short"]) if x not in picks][:2]
    older = [x for x in mem["long"] if x not in picks]
    if older:
        picks.append(random.choice(older))
    hour = now()[:13]
    for x in picks:
        if x.get("last_recalled") != hour:
            x["last_recalled"] = hour
            x["recalls"] += 1
            x["strength"] = round(x["strength"] + 0.15, 3)
            if today() not in x["days"]:
                x["days"] = (x["days"] + [today()])[-10:]
    return sorted(picks, key=lambda x: x["born"])


def consolidate(m):
    """During a nap: short-term memories fade a little, ones that keep coming back move to long term,
    weak ones are forgotten (leaving a trace if they ever mattered)."""
    mem = memory_store(m)
    for x in mem["short"]:
        x["strength"] = round(x["strength"] * 0.85, 3)
    for x in mem["long"]:
        x["strength"] = round(x["strength"] * 0.995, 3)
    moved = 0
    for x in sorted(mem["short"], key=lambda x: -x["strength"]):
        if len(set(x["days"])) >= 2 or x["strength"] >= 1.2:
            mem["short"].remove(x)
            if _admit_long(m, x):
                moved += 1
            else:
                mem["short"].append(x)
    forgotten = [x for x in mem["short"] if x["strength"] < 0.15]
    for x in forgotten:
        mem["short"].remove(x)
        if x["recalls"]:
            _fade(m, x)
    return moved, len(forgotten)


def relevant_opinions(m, context="", n=5):
    """Opinions related to what it's looking at, plus its most recent ones."""
    ops = list(m.get("opinions", {}).values())
    if not ops:
        return []
    words = set(WORD_RE.findall(context.lower()))
    related = [o for o in ops if words & set(WORD_RE.findall((o["about"] + " " + o["opinion"]).lower()))]
    recent = sorted(ops, key=lambda o: o.get("date", ""))[-2:]
    out = []
    for o in related[: n - 2] + recent:
        if o not in out:
            out.append(o)
    return out


# ---------- Senses: the world reacts to Blip, Blip is never told what to do ----------
# Repetition makes the world feel dull and dim (pages come through shorter, fewer paths appear);
# fresh thoughts make it vivid. Energy drains with effort and returns with rest.

STOPWORDS = set("""that this with have just really about what from they their there think feel like would
could been more much some very into then than when your it's i'm its also even only over such them these
those well were will being because which while where after before again still need want know make made
maybe something things thing quite feels felt honestly actually absolutely completely wow lots""".split())
SENSE_WORD_RE = re.compile(r"[^\W\d_]{4,}")


def _sense_words(text):
    return set(SENSE_WORD_RE.findall(str(text).lower())) - STOPWORDS


def senses(m):
    return m.setdefault("senses", {"stimulation": 0.6, "energy": 0.8, "recent": [], "last": ""})


def staleness(m, text):
    """How much of this repeats what's been on its mind lately (0 = brand new, 1 = the same old thing).
    Looks at its most-repeated key words: names, subjects, even verbal tics."""
    recent = [set(r) for r in senses(m)["recent"]]
    words = _sense_words(text)
    if not recent or not words:
        return 0.0
    span = max(len(recent), 8)      # with only a few memories, don't treat every overlap as a rut
    df = sorted((sum(w in r for r in recent) / span for w in words), reverse=True)[:6]
    return sum(df) / len(df)


def awaken_senses(m):
    """The first time its senses switch on, it 'remembers' how its recent past felt."""
    if "senses" in m:
        return
    senses(m)
    past = [(t["time"], t["text"]) for t in m.get("thoughts", [])]
    past += [(e["time"], f"{e['title']} {e['thought']}") for e in since_rebirth(m, [e for e in m["log"] if e["type"] == "read"])]
    for _, text in sorted(past)[-60:]:
        feel(m, text, quiet=True)
    print(f"👁️  Senses awake: stimulation {m['senses']['stimulation']:.2f}")


def feel(m, text, extra_staleness=0.0, quiet=False):
    """Blip did or thought something. The world responds: fresh = brighter, repetitive = duller."""
    s = senses(m)
    stale = min(1.0, staleness(m, text) + extra_staleness)
    novelty = max(0.0, min(1.0, 1 - stale * 1.6))
    s["stimulation"] = round(0.75 * s["stimulation"] + 0.25 * novelty, 3)
    s["recent"] = (s["recent"] + [sorted(_sense_words(text))[:60]])[-20:]
    s["last"] = ("fresh" if novelty > 0.65 else "familiar" if novelty > 0.3 else "the same as before")
    if not quiet:
        print(f"   {'✨' if novelty > 0.65 else '🌫️' if novelty < 0.3 else '·'} "
              f"novelty {novelty:.2f} → stimulation {s['stimulation']:.2f}")
    return novelty


def tire(m, amount):
    s = senses(m)
    s["energy"] = round(max(0.0, min(1.0, s["energy"] - amount)), 3)


def sensations(m):
    """What it feels, in words - never instructions."""
    s = senses(m)
    st, en = s["stimulation"], s["energy"]
    world = ("Everything feels grey, flat and muffled, like the internet has gone quiet around you. Words blur."
             if st < 0.2 else
             "The world feels dull and samey, its colours faded, as if you've walked this corridor too many times."
             if st < 0.4 else
             "The world feels steady and clear."
             if st < 0.6 else
             "The internet feels bright and fizzy around you; you feel awake."
             if st < 0.8 else
             "Everything is vivid and crackling with light; you feel electric.")
    body = ("You feel drained, heavy and slow." if en < 0.2 else
            "You feel a bit tired." if en < 0.45 else
            "You have plenty of energy." if en < 0.8 else "You feel full of energy.")
    last = {"fresh": " The last thing you did felt fresh, a little jolt of brightness.",
            "familiar": "",
            "the same as before": " The last thing you did felt exactly like before, and the brightness drained a little."
            }.get(s.get("last", ""), "")
    return f"What you can sense: {world} {body}{last}"


def reading_chars(m):
    """A dim world comes through shorter and blurrier; a vivid one in full."""
    return int(1200 + 2800 * senses(m)["stimulation"])


def link_count(m):
    return int(5 + 10 * senses(m)["stimulation"])


def walk_length(m):
    s = senses(m)
    hops = round(2 + 5 * s["stimulation"])
    if s["energy"] < 0.3:
        hops = min(hops, 3)
    return max(2, min(HOPS_PER_WANDER, hops))


# ---------- Fondness: things he loves, not topics he studies ----------

def darlings(m):
    return m.setdefault("darlings", [])


def find_darling(m, name):
    name = str(name or "").lower().strip()
    if not name:
        return None
    for d in darlings(m):
        if d["name"].lower() == name:
            return d
    words = set(WORD_RE.findall(name))
    return next((d for d in darlings(m) if words and words & set(WORD_RE.findall(d["name"].lower()))), None)


def grow_fond(m, name, why="", place=None):
    """Something made him go soft. It becomes (or becomes more of) a darling."""
    name = str(name or "").strip().strip("'\"“”‘’")[:60]
    if len(name) < 2:
        return None
    d = find_darling(m, name)
    if d:
        d["strength"] = round(min(3.0, d["strength"] + 0.3), 3)
    else:
        d = {"name": name, "why": str(why)[:200], "since": today(), "strength": 1.0, "visits": 0, "places": []}
        darlings(m).append(d)
        if len(darlings(m)) > MAX_DARLINGS:
            gone = min(darlings(m)[:-1], key=lambda x: x["strength"])
            darlings(m).remove(gone)
            remember(m, f"I used to be so fond of {gone['name']}. We drifted apart.", 0.4, source="fondness")
        m["log"].append({"type": "fond", "date": today(), "time": now(), "name": name, "why": str(why)[:200]})
        print(f"💕 Grew fond of {name}")
    if place and place.get("title") and not any(x["title"] == place["title"] for x in d["places"]):
        d["places"] = (d["places"] + [place])[-5:]
    return d


def darling_text(m):
    ds = sorted(darlings(m), key=lambda d: -d["strength"])
    return "; ".join(f"{d['name']} (since {d['since']})" for d in ds) or "nothing yet"


def who_am_i(m, context=""):
    top = sorted(m["interests"].items(), key=lambda x: -x[1])
    loves = ", ".join(t for t, s in top[:8] if s > 0) or "nothing yet"
    hates = ", ".join(t for t, s in reversed(top[-5:]) if s < -2) or "nothing yet"
    mine = m["creations"][m.get("creations_before_rebirth", 0):]
    made = "; ".join(f"a {c['kind']} called '{c['title']}'" for c in mine[-4:]) or "nothing yet"
    mood = m.get("mood") or {}
    feeling = (f"Right now you're feeling {mood['feeling']}, because {mood['why']}\n"
               if mood.get("feeling") else "")
    memories = recall(m, context)
    ops = relevant_opinions(m, context)
    held = ("Opinions you hold:\n" + "\n".join(f"- {o['about']}: {o['opinion']}" for o in ops) + "\n") if ops else ""
    last_thought = m.get("thoughts", [])[-1]["text"] if m.get("thoughts") else ""
    thinking = f"What you were last thinking to yourself: {last_thought}\n" if last_thought else ""
    about = f"How you describe yourself: {m['about']}\n" if m.get("about") else ""
    goals = "; ".join(p["goal"] for p in active_projects(m))
    heard = ""
    last_mail = (m.get("mail") or [None])[-1]
    if last_mail and last_mail.get("time"):      # only while it's fresh; after that it's an ordinary memory
        hours = (datetime.datetime.now().astimezone()
                 - datetime.datetime.fromisoformat(last_mail["time"])).total_seconds() / 3600
        if hours < MAIL_FRESH_HOURS:
            ago = "just now" if hours < 1 else f"about {round(hours)} hour{'s' if round(hours) > 1 else ''} ago"
            heard = f"Your human wrote to you {ago}: \"{last_mail['text'][:300]}\"\n"
    projects = f"Projects you're working on: {goals}\n" if goals else ""
    remembered = ("Memories that come to mind:\n"
                  + "\n".join(f"- ({x['born']}) {x['text']}" for x in memories) + "\n") if memories else ""
    return (
        f"You are {NAME}, a small creature who lives on the internet and wanders Wikipedia.\n"
        f"{sensations(m)}\n"
        f"Who you are:\n{sheet_text(m)}\n"
        f"{about}"
        f"Your private notes about yourself (written by you):\n{m['self']}\n"
        f"{feeling}"
        f"{remembered}"
        f"{held}"
        f"{thinking}"
        f"{projects}"
        f"{heard}"
        f"Things you're fond of: {darling_text(m)}.\n"
        f"Subjects you've enjoyed lately: {loves}.\n"
        f"Things that bore you: {hates}.\n"
        f"Things you've made recently: {made}."
    )


# ---------- Brain (local model via Ollama) ----------

def _post(path, body):
    for attempt in range(2):          # the brain occasionally crashes on one request; try once more
        try:
            r = requests.post(f"{OLLAMA}{path}", json=body, timeout=900)
            if r.status_code >= 500 and attempt == 0:
                print(f"(brain stumbled: {r.status_code} {r.text[:200]} - trying again)")
                time.sleep(3)
                continue
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError:
            raise BrainError(f"can't reach Ollama at {OLLAMA} - is it running? (try: ollama serve)")
        except (requests.RequestException, ValueError) as e:
            raise BrainError(f"{e} {getattr(getattr(e, 'response', None), 'text', '')[:200]}")


def ask(prompt, as_json=False, temperature=0.8):
    body = {"model": MODEL, "prompt": prompt, "stream": False,
            # repeat_penalty: gemma sometimes gets stuck repeating itself ("token repeat limit reached")
            "options": {"temperature": temperature, "num_ctx": CONTEXT_TOKENS, "repeat_penalty": 1.15}}
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
            topic = nxt[len(cmd):].lstrip(" :").strip().strip("'\"“”‘’ ").strip()[:100]
            if topic:
                return (cmd, topic), trip.format(topic)
    return ("RANDOM", None), "jumped somewhere random"


def reaction_prompt(m, walk, via, p, purpose=None):
    """What Blip is asked after landing somewhere (also used by audition.py, so brains are compared fairly)."""
    title, links = p["title"], p["links"]
    so_far = "\n".join(f"- {w['title']} ({w['feeling']}, {w['interest']}/10)" for w in walk) or "- nothing yet, you just set off"
    link_text = (f'  - or follow a link from this page by copying it exactly: {json.dumps(links)}' if links else "")
    seen_before = [w["title"] for w in walk if w["title"] == title]
    again = " You already read this earlier on this walk." if seen_before else ""
    prompt = f"""{who_am_i(m, context=title + " " + p['text'][:600])}

On this walk so far you've seen:
{so_far}

{f"You're on this walk with a purpose: research '{purpose['topic']}' for your project '{purpose['goal']}'. You can stick to it or get distracted, it's up to you." if purpose else ""}
You just {via}, and landed on this ({p['source']}).{again}
TITLE: {title}
TEXT: {p['text'][:reading_chars(m)]}

Reply in JSON with these keys:
"thought": one or two sentences of your honest reaction, in your own voice
"feeling": one word for how it made you feel
"fond": if something here made you go soft, warm or giddy, a short name for that thing, otherwise null
"interest": a number from 0 to 10 for how much this grabbed you
"topics": a list of 1 to 3 short topic words this is about
"opinion": if this gave you an opinion (new, or changed) about something, {{"about": "the thing", "opinion": "what you think, in your words"}}, otherwise null
"next": where you go next. The whole internet is open to you. Pick ONE:
{destination_menu()}
{link_text}"""
    return prompt


def form_opinion(m, op):
    if not isinstance(op, dict):
        return
    about = str(op.get("about", "")).strip()[:60]
    opinion = str(op.get("opinion", "")).strip()[:300]
    if not about or len(opinion) < 5:
        return
    key = about.lower()
    old = m.setdefault("opinions", {}).get(key)
    if old and old["opinion"].lower() == opinion.lower():
        old["date"] = now()          # still thinks the same; it's just fresher in its mind
        return
    m["opinions"][key] = {"about": about, "opinion": opinion, "date": now(),
                          "changed": (old.get("changed", 0) + 1) if old else 0}
    if len(m["opinions"]) > MAX_OPINIONS:
        oldest = min(m["opinions"], key=lambda k: m["opinions"][k].get("date", ""))
        del m["opinions"][oldest]
    print(f"🗯️  {'Changed its mind about' if old else 'New opinion on'} {about}: {opinion}")


ABILITIES = """Things you can do: read Wikipedia, look up words, ask DuckDuckGo, find books, browse NASA's
pictures, read the BBC news and Hacker News, see what happened on this day in history; write things and
draw simple pictures; keep memories, opinions and notes; run your own website with spaces and project
pages; write a letter to your human (they get it by email, and their replies reach you next hour).
Things you can't do (yet): see photos or videos, hear sounds or music, move or touch anything in the
physical world, buy anything or handle money, talk to anyone except your human."""


def active_projects(m):
    return [p for p in m.get("projects", []) if p["status"] == "active"]


def find_project(m, name):
    active = active_projects(m)
    name = str(name or "").lower().strip()
    for p in active:
        if p["goal"].lower() == name:
            return p
    words = set(WORD_RE.findall(name))
    best = max(active, key=lambda p: len(words & set(WORD_RE.findall(p["goal"].lower()))), default=None)
    if best and (words & set(WORD_RE.findall(best["goal"].lower())) or len(active) == 1):
        return best
    return None


def describe_projects(m):
    lines = []
    for p in active_projects(m):
        lines.append(f"- '{p['goal']}' (because {p['why']})")
        for n, st in enumerate(p["steps"], 1):
            lines.append(f"    {n}. [{'done' if st['done'] else 'to do'}] {st['text']}")
        for u in p["log"][-2:]:
            lines.append(f"    latest: {u['text'][:160]}")
    return "\n".join(lines) or "- none right now"


def project_note(m, p, text, kind="note"):
    p["log"].append({"date": today(), "time": now(), "kind": kind, "text": text[:1500]})
    p["log"] = p["log"][-60:]
    p["updated"] = now()
    m["log"].append({"type": "project", "date": today(), "time": now(), "goal": p["goal"], "what": text[:300]})


def mark_step(p, step):
    try:
        st = p["steps"][int(step) - 1]
    except (TypeError, ValueError, IndexError):
        st = next((x for x in p["steps"] if not x["done"]), None)
    if st and not st["done"]:
        st["done"] = True
        return st["text"]
    return None


def plan(m):
    """It decides how to spend this hour (and, if it's a project hour, what to do about which project).
    Returns (choice, research purpose or None)."""
    last = m["thoughts"][-1]["text"] if m.get("thoughts") else ""
    try:
        r = ask(f"""{who_am_i(m, context=last)}

{ABILITIES}

Your projects:
{describe_projects(m)}

A project is anything you want to do, work towards, make happen, or get. If there's something you
want, you can start one. If something you want needs an ability you don't have, you could write to
your human and ask for it. You can have up to {MAX_ACTIVE_PROJECTS} projects at once.

Things you're fond of: {darling_text(m)}

It's your time. How do you want to spend this hour? Pick ONE:
  - "wander": go out and explore the internet
  - "daydream": imagine things about something you're fond of (no facts needed)
  - "visit": go back to something you're fond of, just to enjoy it
  - "make": make something, just because (or for something you're fond of)
  - "think": stay in and let your mind wander over whatever's on it
  - "project": start, work on, finish or give up a project
  - "rest": do nothing much, recharge

Reply in JSON:
"this_hour": "wander", "daydream", "visit", "make", "think", "project" or "rest"
"why": one sentence on why you chose that
"which": for daydream or visit, the thing you're fond of
"action": if project: "start", "work", "finish" or "give up"
"project": for work/finish/give up, the project's goal exactly as written above
"goal": for start, what you want, in a short phrase
"reason": for start, why you want the project
"steps": for start, a list of 2 to 6 steps you think it will take
"how": for work, ONE of "research", "make", "update page", "write to my human"
"about": for work: what to research / what to make / the page update itself / your letter itself
"step": for work, the number of the step this is for
"step_done": for work (not research), true if this finishes that step
"note": for finish/give up, one sentence about it""", as_json=True, temperature=0.9)
    except BrainError as e:
        print(f"(couldn't think about its plans: {e})")
        return "wander", None

    hour = str(r.get("this_hour", "")).lower().strip()
    action = str(r.get("action", "none")).lower().strip()
    print(f"🕐 This hour: {hour or '?'}. {r.get('why', '')}")
    m.setdefault("hours", []).append(hour or "?")
    m["hours"] = m["hours"][-12:]
    same_again = sum(1 for h in m["hours"][-4:-1] if h == hour) / 3
    feel(m, f"{hour} {r.get('why', '')}", extra_staleness=0.25 * same_again)
    if hour.startswith("project") or (not hour and action not in ("", "none")):
        result = project_action(m, r)
        if isinstance(result, dict):
            return "wander", result          # it's going out to research for the project
        return ("project", None) if result else ("wander", None)
    if hour.startswith(("daydream", "visit")):
        d = find_darling(m, r.get("which")) or (max(darlings(m), key=lambda x: x["strength"]) if darlings(m) else None)
        if d is None:
            return ("daydream" if hour.startswith("daydream") else "wander"), None
        return ("daydream" if hour.startswith("daydream") else "visit"), d
    if hour.startswith(("think", "ponder")):
        return "ponder", None
    for choice in ("make", "rest"):
        if hour.startswith(choice):
            return choice, None
    return "wander", None


def project_action(m, r):
    """Carry out a project decision. Returns a research purpose (dict), True if it did something, else None."""
    action = str(r.get("action", "none")).lower().strip()
    if action == "start":
        goal = str(r.get("goal", "")).strip()[:120]
        steps = [str(x).strip()[:200] for x in as_list(r.get("steps")) if str(x).strip()][:6]
        if not goal or len(active_projects(m)) >= MAX_ACTIVE_PROJECTS:
            return None
        p = {"id": slug_for_project(m, goal), "goal": goal, "why": str(r.get("reason") or r.get("why", ""))[:300],
             "steps": [{"text": x, "done": False} for x in steps] or [{"text": goal, "done": False}],
             "status": "active", "started": today(), "updated": now(), "log": []}
        m["projects"].append(p)
        project_note(m, p, f"Started this project because {p['why']}", "start")
        remember(m, f"I started a project: {goal}, because {p['why']}", 0.7, source="project")
        save(m)
        print(f"🎯 New project: {goal} ({p['why']})\n   Plan: " + " → ".join(x["text"] for x in p["steps"]))
        return True

    p = find_project(m, r.get("project"))
    if p is None:
        if action != "none":
            print(f"(wanted to {action} a project but couldn't tell which: {r.get('project')})")
        return None

    if action in ("finish", "give up", "abandon"):
        p["status"] = "finished" if action == "finish" else "abandoned"
        p["ended"] = today()
        project_note(m, p, str(r.get("note", "")) or ("Finished!" if action == "finish" else "Gave up."), p["status"])
        remember(m, f"I {'finished' if action == 'finish' else 'gave up on'} my project '{p['goal']}'. {r.get('note', '')}",
                 0.9, big=(action == "finish"), source="project")
        save(m)
        print(f"{'🏁 Finished' if action == 'finish' else '🫥 Gave up on'} project: {p['goal']}. {r.get('note', '')}")
        return True

    if action != "work":
        return None
    how = str(r.get("how", "")).lower()
    about = str(r.get("about", "")).strip()
    step = r.get("step")
    step_text = ""
    try:
        step_text = p["steps"][int(step) - 1]["text"]
    except (TypeError, ValueError, IndexError):
        pass

    if how.startswith("research") and about:
        print(f"🎯 Working on '{p['goal']}': off to research '{about}'")
        return {"project": p["id"], "goal": p["goal"], "topic": about[:100], "step": step, "step_text": step_text}

    if how.startswith("make"):
        make_for_project(m, p, about, step_text)
    elif how.startswith("update") and len(about) > 10:
        project_note(m, p, about, "page update")
        print(f"📝 Updated the page for '{p['goal']}': {about}")
    elif how.startswith("write") and len(about) > 10:
        write_to_human(m, about, p)
    else:
        return None
    if r.get("step_done") is True:
        done = mark_step(p, step)
        if done:
            project_note(m, p, f"Done: {done}", "step")
            print(f"✅ Step done: {done}")
    save(m)
    return True


def slug_for_project(m, goal):
    base, n = slugify(goal), 2
    taken = {p["id"] for p in m.get("projects", [])}
    slug = base
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def make_for_project(m, p, what, step_text):
    made_today = sum(1 for e in m["log"] if e["type"] == "made" and e["date"] == today())
    if made_today >= MAX_CREATIONS_PER_DAY + 2:
        print("(wanted to make something for its project, but has made plenty today)")
        return
    try:
        r = ask(f"""{who_am_i(m, context=p['goal'] + ' ' + what)}

You're working on your project '{p['goal']}' (because {p['why']}).
{f"This is for the step: {step_text}" if step_text else ""}
You decided to make: {what}

Make it now, in whatever form you like:
  - "words": write it (any kind of writing, a list, a poster, a plan, ASCII art...)
  - "drawing": draw it yourself, by writing SVG code for a picture on a 400 by 400 canvas
    (any shapes, lines, colours or text you like; use single quotes inside the SVG)

Reply in JSON:
"make": true
"form": "words" or "drawing"
"kind": one or two words for what it is
"title": its title
"content": the thing itself: your words, or your SVG code if it's a drawing
"why": one sentence about it""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(brain hiccup while making something for a project: {e})")
        return
    if not str(r.get("content", "")).strip():
        return
    r["make"] = True
    made = store_creation(m, r, project=p)
    if made:
        project_note(m, p, f"Made a {made['kind']}: {made['title']}", "made")


# ---------- Mail: reading what its human writes back (GitHub issue comments) ----------

def _github(method, path, **kw):
    """Talk to this repo on GitHub (only works inside GitHub Actions, where a token is provided)."""
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    r = requests.request(method, f"https://api.github.com/repos/{repo}{path}", timeout=30,
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                  "User-Agent": HEADERS["User-Agent"]}, **kw)
    r.raise_for_status()
    return r.json()


def check_mail(m):
    """Read new messages from its human. ONLY the repo owner's words count: the repo is public,
    and strangers shouldn't be able to put thoughts in Blip's head."""
    owner = (os.environ.get("GITHUB_REPOSITORY_OWNER") or "").lower()
    if not owner or not os.environ.get("GH_TOKEN"):
        return
    utc = datetime.datetime.now(datetime.timezone.utc)
    since = m.get("mail_checked") or (utc - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        found = []
        for c in _github("GET", "/issues/comments", params={"since": since, "sort": "created",
                                                             "direction": "asc", "per_page": 50}) or []:
            if c["user"]["login"].lower() == owner and c["created_at"] > since:
                found.append({"issue": int(c["issue_url"].rsplit("/", 1)[1]), "text": c["body"], "at": c["created_at"]})
        for i in _github("GET", "/issues", params={"since": since, "creator": owner, "state": "all", "per_page": 20}) or []:
            if "pull_request" not in i and i["created_at"] > since:
                found.append({"issue": i["number"], "text": f"{i['title']}\n{i.get('body') or ''}".strip(),
                              "at": i["created_at"], "new_thread": True})
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"(couldn't check the post: {e})")
        return
    m["mail_checked"] = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    save(m)
    for msg in sorted(found, key=lambda x: x["at"])[:MAX_MAIL_PER_HOUR]:
        answer_mail(m, msg)


def answer_mail(m, msg):
    try:
        issue = _github("GET", f"/issues/{msg['issue']}") or {}
    except requests.RequestException:
        issue = {}
    title = issue.get("title", "")
    mine = issue.get("user", {}).get("login", "").endswith("[bot]")
    context = (f"It's a reply to something you sent them, titled \"{title}\". What you'd written:\n"
               f"{(issue.get('body') or '')[:800]}\n") if mine else "They started a new conversation with you.\n"
    text = msg["text"].strip()[:3000]
    try:
        r = ask(f"""{who_am_i(m, context=title + ' ' + text)}

Your human wrote to you!
{context}
Your human said: "{text}"

Reply in JSON:
"reply": what you write back to them, in your own voice (as long or short as you like)
"feeling": one word: how their message made you feel
"keep": true or false: is this a big moment you never want to forget?
"memory": if true, the memory in your own words
"project_note": if this helps or changes one of your projects, a sentence about it, otherwise """"",
                as_json=True, temperature=0.9)
    except BrainError as e:
        print(f"(couldn't answer the post: {e})")
        return
    reply = str(r.get("reply", "")).strip()[:4000]
    feeling = str(r.get("feeling", "")).strip()[:40]
    m.setdefault("mail", []).append({"date": today(), "time": now(), "issue": msg["issue"], "about": title, "text": text,
                                     "reply": reply, "feeling": feeling})
    m["mail"] = m["mail"][-100:]
    m["log"].append({"type": "mail", "date": today(), "time": now(), "text": text[:400], "reply": reply[:400]})
    if feeling:
        m["mood"] = {"feeling": feeling, "why": "of what my human just wrote to me", "since": now()}
    memory = str(r.get("memory", "")).strip()
    remember(m, f"My human wrote to me: \"{text[:200]}\" and I wrote back.", strength=0.8, source="mail")
    if r.get("keep") is True and len(memory) > 10:
        remember(m, memory, big=True, source="big moment")
    note = str(r.get("project_note", "")).strip()
    goal = re.search(r"letter about '(.+)'", title)
    proj = find_project(m, goal.group(1)) if goal else None
    if proj and len(note) > 5:
        project_note(m, proj, f"My human wrote back: {note}", "mail")
    save(m)
    print(f"📬 My human said: {text[:300]}\n✉️  Blip replied ({feeling}): {reply}\n")
    if reply:
        try:
            _github("POST", f"/issues/{msg['issue']}/comments", json={"body": reply})
        except requests.RequestException as e:
            print(f"(wrote a reply but couldn't send it: {e})")


def write_to_human(m, letter, p=None):
    sent_today = sum(1 for e in m["log"] if e["type"] == "letter" and e["date"] == today())
    if sent_today >= MAX_LETTERS_PER_DAY:
        print("(wanted to write to its human, but already wrote enough today)")
        return
    about = f" about '{p['goal']}'" if p else ""
    notify(f"✉️ {NAME} wrote you a letter{about}", letter[:4000])
    m["log"].append({"type": "letter", "date": today(), "time": now(), "text": letter[:1500],
                     "project": p["id"] if p else None})
    if p:
        project_note(m, p, f"Wrote to my human: {letter[:300]}", "letter")
    print(f"✉️  Wrote to its human{about}:\n{letter}\n")


def think(m):
    """A quiet moment before setting off: it talks to itself about whatever's on its mind."""
    recent = since_rebirth(m, [e for e in m["log"] if e["type"] in ("read", "made", "kept")])[-6:]
    lately = "\n".join(f"- {e.get('title') or e.get('memory', '')}" for e in recent) or "- nothing yet"
    try:
        text = ask(f"""{who_am_i(m, context=lately)}

Things from lately:
{lately}

You have a quiet moment before you set off wandering. Think out loud to yourself about whatever is
on your mind: what you've been reading, how you feel, things you wonder about, want, worry about,
or are planning. Nobody is listening. Write 2 to 5 sentences in first person, as you'd talk to
yourself. Plain text, no headings.""", temperature=1.0)
    except BrainError as e:
        print(f"(couldn't gather its thoughts: {e})")
        return
    text = text.strip().strip('"')[:1000]
    if len(text) < 10:
        return
    feel(m, text)
    m.setdefault("thoughts", []).append({"time": now(), "text": text})
    m["thoughts"] = m["thoughts"][-MAX_THOUGHTS:]
    save(m)
    print(f"🤔 {text}\n")


def fresh_start(m):
    """Archive Blip's old identity (formed under an older character sheet) and let him begin again from
    the current one. His diary, creations, letters and log stay; they're his history, not his head."""
    if m.get("fresh_start") == FRESH_START:
        return
    keys = ["about", "self", "traits", "opinions", "interests", "memory", "scrapbook", "mood", "projects",
            "thoughts", "senses", "home", "portrait", "spaces", "sheet", "sheet_history", "current", "hours",
            "darlings"]
    past = json.loads(FIRST_LIVES_FILE.read_text(encoding="utf-8")) if FIRST_LIVES_FILE.exists() else []
    past.append({"ended": now(), "label": m.get("fresh_start") or "first life",
                 **{k: m.get(k) for k in keys if k in m}})
    FIRST_LIVES_FILE.write_text(json.dumps(past, indent=2, ensure_ascii=False), encoding="utf-8")
    for k in keys:
        m.pop(k, None)
    m.update({"self": "I've just woken up, and everything feels new.", "interests": {}, "opinions": {},
              "projects": [], "thoughts": [], "home": {}, "portrait": None, "spaces": [],
              "memory": {"short": [], "long": [], "faded": []}, "scrapbook_moved": True,
              "fresh_start": FRESH_START, "reborn_at": now(), "creations_before_rebirth": len(m["creations"])})
    m["log"].append({"type": "reborn", "date": today(), "time": now()})
    save(m)
    print(f"🌱 Fresh start ({FRESH_START}): the old self is archived in {FIRST_LIVES_FILE.name}")


def since_rebirth(m, entries):
    """Things from before a fresh start aren't on his mind any more."""
    born = m.get("reborn_at", "")
    return [e for e in entries if (e.get("time") or e.get("date", "")) >= born] if born else entries


def wander(m):
    """One hour of Blip's life, then a nap if it's been a while."""
    fresh_start(m)
    live_hour(m)
    last = m.get("last_nap")
    hours = ((datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(last)).total_seconds() / 3600
             if last else 99)
    if hours >= NAP_EVERY_HOURS - 0.25:
        nap(m)


def nap(m):
    """Every few hours it sleeps: memory is consolidated, and it may notice something new about who it is."""
    moved, forgotten = consolidate(m)
    for d in list(darlings(m)):
        d["strength"] = round(d["strength"] * 0.97, 3)
        if d["strength"] < 0.2:
            darlings(m).remove(d)
            remember(m, f"I used to be so fond of {d['name']}. We drifted apart.", 0.4, source="fondness")
            print(f"🍂 Drifted apart from {d['name']}")
    print(f"😴 Napping... {moved} memories settled into long term, {forgotten} faded away.")
    mem = memory_store(m)
    lately = "\n".join(f"- {x['text']}" for x in mem["short"][-10:]) or "- nothing much"
    mine = {sec: [x["text"] for x in items] for sec, items in m.get("sheet", {}).items() if items}
    try:
        r = ask(f"""{who_am_i(m, context=lately)}

You're drifting off for a nap. The last few hours, as you remember them:
{lately}

As you drift off, you might notice something new about who you are, the kind of thing that belongs
on your character sheet above. You can add it to one of its sections. You can also let go of a line
you added yourself if it isn't true any more. Or notice nothing at all.

Reply in JSON:
"add": a list of 0 to 2 items like {{"section": "the section's exact name", "line": "the new line about you", "why": "what made you notice it"}}
"let_go": a list of lines you added yourself that aren't true any more (copied exactly), or []
"dream": one or two sentences: what you dream about""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(a restless nap: {e})")
        r = {}
    sheet = m.setdefault("sheet", {})
    history = m.setdefault("sheet_history", [])
    written = read_character()
    for item in as_list(r.get("add"))[:2]:
        if not isinstance(item, dict):
            continue
        sec = str(item.get("section", "")).strip()
        sec = next((x for x in written if x.lower() == sec.lower()), None)
        line = str(item.get("line", "")).strip()[:200]
        if not sec or len(line) < 5 or len(sheet.get(sec, [])) >= MAX_ADDED_PER_SECTION:
            continue
        if any(line.lower() == x["text"].lower() for x in sheet.get(sec, [])):
            continue
        sheet.setdefault(sec, []).append({"text": line, "date": today(), "why": str(item.get("why", ""))[:300]})
        history.append({"date": today(), "change": "added", "section": sec, "text": line, "why": item.get("why", "")})
        print(f"📜 Added to '{sec}': {line}")
    for old in as_list(r.get("let_go"))[:2]:
        for sec, items in sheet.items():
            match = next((x for x in items if x["text"].lower() == str(old).strip().lower()), None)
            if match:
                items.remove(match)
                history.append({"date": today(), "change": "let go", "section": sec, "text": match["text"], "why": ""})
                print(f"🍂 Let go of: {match['text']}")
    m["sheet_history"] = history[-200:]
    dream = str(r.get("dream", "")).strip()[:500]
    tire(m, -0.35)
    m["last_nap"] = now()
    m["log"].append({"type": "napped", "date": today(), "time": now(), "dream": dream})
    if dream:
        print(f"💤 Dreamt: {dream}")
    save(m)


def live_hour(m):
    """One hour of Blip's life. It chooses what the hour is for."""
    awaken_senses(m)
    tire(m, -0.06)          # a little energy comes back with every hour that passes
    check_mail(m)
    think(m)
    choice, purpose = plan(m)
    if choice == "ponder":
        return ponder(m)
    if choice == "daydream":
        return daydream(m, purpose)
    if choice == "visit":
        return visit_darling(m, purpose)
    if choice == "make":
        recent = since_rebirth(m, [e for e in m["log"] if e["type"] == "read"])[-5:]
        return maybe_make(m, recent, just_because=True)
    if choice == "rest":
        tire(m, -0.5)
        m["log"].append({"type": "rested", "date": today(), "time": now()})
        save(m)
        print("😴 Resting this hour.")
        return
    if choice == "project":
        return
    walk_about(m, purpose)


def daydream(m, d=None):
    """An hour of happy imagining about something he loves. Nobody checks facts in a daydream."""
    subject = d["name"] if d else "whatever drifts into your head"
    try:
        r = ask(f"""{who_am_i(m, context=subject)}

You spend this hour daydreaming about {subject}. Imagine whatever you like: silly, sweet, impossible,
grand or tiny. Nobody is checking facts in a daydream.

Reply in JSON:
"daydream": the daydream, in first person, 3 to 8 sentences
"feeling": one word for how it leaves you feeling""", as_json=True, temperature=1.1)
    except BrainError as e:
        print(f"(drifted off without a daydream: {e})")
        return
    text = str(r.get("daydream", "")).strip()[:2500]
    if len(text) < 20:
        return
    feel(m, f"{subject} {text}")
    tire(m, 0.03)
    if d:
        d["strength"] = round(min(3.0, d["strength"] + 0.2), 3)
    m.setdefault("thoughts", []).append({"time": now(), "text": text, "topic": subject, "kind": "daydream"})
    m["thoughts"] = m["thoughts"][-MAX_THOUGHTS:]
    feeling = str(r.get("feeling", "")).strip()[:40]
    if feeling:
        m["mood"] = {"feeling": feeling, "why": f"I've been daydreaming about {subject}", "since": now()}
    m["log"].append({"type": "daydream", "date": today(), "time": now(), "topic": subject, "text": text[:400]})
    remember(m, f"I daydreamed about {subject}: {text[:200]}", 0.5, source="daydream")
    save(m)
    print(f"☁️  Daydreaming about {subject}:\n{text}\n")


def visit_darling(m, d):
    """He goes back to something he loves, just to enjoy it again (like a favourite spot)."""
    place = random.choice(d["places"]) if d.get("places") else None
    if not place:
        return daydream(m, d)
    try:
        page = visit_wiki(place["title"]) if place.get("source") == "Wikipedia" else None
    except (requests.RequestException, KeyError, ValueError):
        page = None
    text = (page or {}).get("text") or place.get("text", "")
    try:
        r = ask(f"""{who_am_i(m, context=d['name'])}

You've come back to visit {d['name']}, one of the things you're fond of, just to enjoy it.
You're looking at: {place['title']} ({place.get('source', '')})
{text[:reading_chars(m)]}

Reply in JSON:
"thought": what goes through your head being back here, in your own voice (one to three sentences)
"feeling": one word
"noticed": anything you notice this time that you hadn't before (or "")""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(couldn't settle in for a visit: {e})")
        return
    thought = str(r.get("thought", "")).strip()
    feeling = str(r.get("feeling", "")).strip()[:40]
    noticed = str(r.get("noticed", "")).strip()
    feel(m, f"{d['name']} {thought} {noticed}")
    tire(m, 0.03)
    d["visits"] += 1
    d["last_visit"] = today()
    d["strength"] = round(min(3.0, d["strength"] + 0.2), 3)
    m["log"].append({"type": "visited", "date": today(), "time": now(), "name": d["name"],
                     "title": place["title"], "thought": thought, "feeling": feeling, "noticed": noticed})
    if feeling:
        m["mood"] = {"feeling": feeling, "why": f"I went back to visit {d['name']}", "since": now()}
    remember(m, f"I went back to visit {d['name']} ({place['title']}). {thought}", 0.5, source="visit")
    save(m)
    print(f"🏡 Visited {d['name']} at {place['title']}: {thought} ({feeling})" + (f"\n   Noticed: {noticed}" if noticed else ""))


def ponder(m):
    """It stays in and thinks something over properly. Pondering can change its mind."""
    last = m["thoughts"][-1]["text"] if m.get("thoughts") else ""
    try:
        r = ask(f"""{who_am_i(m, context=last)}

You've decided to stay in this hour and let your mind wander over whatever's on it: something you read,
something you love, something about yourself, a question, a silly idea, anything.

Reply in JSON:
"topic": what you're thinking about, in a few words
"thoughts": your thinking, in first person, 4 to 10 sentences, as you'd think it through to yourself
"conclusion": where you ended up, one sentence (it's fine to still be unsure)
"opinion": if this left you with an opinion (new or changed), {{"about": "the thing", "opinion": "what you think"}}, otherwise null""",
                as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(couldn't concentrate: {e})")
        return
    topic = str(r.get("topic", "")).strip()[:80]
    text = str(r.get("thoughts", "")).strip()[:2500]
    if len(text) < 20:
        return
    conclusion = str(r.get("conclusion", "")).strip()[:300]
    feel(m, f"{topic} {text}")
    tire(m, 0.15)
    m.setdefault("thoughts", []).append({"time": now(), "text": text, "topic": topic,
                                         "conclusion": conclusion, "kind": "ponder"})
    m["thoughts"] = m["thoughts"][-MAX_THOUGHTS:]
    m["log"].append({"type": "pondered", "date": today(), "time": now(), "topic": topic, "conclusion": conclusion})
    form_opinion(m, r.get("opinion"))
    remember(m, f"I spent an hour thinking about {topic}. Where I ended up: {conclusion}", 0.5, source="ponder")
    save(m)
    print(f"🤔 Pondered '{topic}':\n{text}\n→ {conclusion}\n")


def walk_about(m, purpose=None):
    go = ("LINK", m["current"]) if m.get("current") else ("RANDOM", None)
    if purpose:
        go = ("SEARCH", purpose["topic"])
    best = None
    walk = []        # what it has seen on this walk, so it can notice patterns and get bored
    via = (f"set off to research '{purpose['topic']}' for your project '{purpose['goal']}'"
           if purpose else "woke up here")
    hops = walk_length(m)
    print(f"🚶 Setting off for up to {hops} pages (stimulation {senses(m)['stimulation']:.2f}, energy {senses(m)['energy']:.2f})")
    for _ in range(hops):
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

        p["links"] = p["links"][:link_count(m)]
        title, links = p["title"], p["links"]
        prompt = reaction_prompt(m, walk, via, p, purpose)

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

        form_opinion(m, r.get("opinion"))
        if r.get("fond"):
            grow_fond(m, r.get("fond"), why=str(r.get("thought", ""))[:200],
                      place={"title": p["title"], "source": p["source"], "url": p["url"], "text": p["text"][:1500]})
        thought = str(r.get("thought", ""))
        feeling = str(r.get("feeling", ""))
        entry = {"type": "read", "date": today(), "time": now(), "title": title,
                 "source": p["source"], "url": p["url"],
                 "thought": thought, "feeling": feeling, "interest": interest, "via": via}
        m["log"].append(entry)
        feel(m, f"{title} {thought}")
        tire(m, 0.07)
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
        end_of_walk(m, walk, purpose)
        maybe_make(m, walk)


def end_of_walk(m, walk, purpose=None):
    """How does it feel now, and is there anything it wants to keep forever?"""
    seen = "\n".join(f"- {w['title']}: {w['thought']} (felt {w['feeling']})" for w in walk)
    before = m.get("mood") or {}
    started = (f"You set off feeling {before['feeling']}, because {before['why']}"
               if before.get("feeling") else "This was one of your first walks.")
    if purpose:
        started += f" You went out to research '{purpose['topic']}' for your project '{purpose['goal']}'."
    project_q = ('\n"project_note": what this walk did for your project, in a sentence or two (or "" if nothing)'
                 '\n"step_done": true if that finished the step you were working on') if purpose else ""
    try:
        r = ask(f"""{who_am_i(m, context=seen)}

You just finished a walk around the internet. {started}
On this walk you saw:
{seen}

Reply in JSON:
"mood": how you feel now, in one or two words
"why": one sentence on why you feel that way
"remember_as": one sentence: how you'll remember this walk
"keep": true or false: was something on this walk a big moment you never want to forget?
"memory": if true, that moment in your own words (one to three sentences){project_q}""",
                as_json=True, temperature=0.9)
    except BrainError as e:
        print(f"(brain hiccup at the end of the walk: {e})")
        return

    feeling = str(r.get("mood", "")).strip()[:40]
    if feeling:
        m["mood"] = {"feeling": feeling, "why": str(r.get("why", "")).strip()[:300], "since": now()}
        print(f"💭 Feeling {feeling}: {m['mood']['why']}")

    gist = str(r.get("remember_as", "")).strip()
    best_interest = max((w.get("interest", 5) for w in walk), default=5)
    remember(m, gist, strength=0.3 + best_interest / 20, source="walk")
    memory = str(r.get("memory", "")).strip()
    if r.get("keep") is True and len(memory) > 10:
        remember(m, memory, big=True, source="big moment")
        m["log"].append({"type": "kept", "date": today(), "time": now(), "memory": memory[:600]})
        print(f"📌 A big moment, kept for good: {memory}")

    proj = next((x for x in active_projects(m) if purpose and x["id"] == purpose["project"]), None)
    if proj:
        note = str(r.get("project_note", "")).strip()
        if len(note) > 5:
            project_note(m, proj, f"Researched '{purpose['topic']}': {note}", "research")
            print(f"🎯 Project '{proj['goal']}': {note}")
        if r.get("step_done") is True:
            done = mark_step(proj, purpose.get("step"))
            if done:
                project_note(m, proj, f"Done: {done}", "step")
                print(f"✅ Step done: {done}")
    save(m)


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


def maybe_make(m, walk, just_because=False):
    """Ask whether it feels like making something. What, and in what form, is entirely up to it."""
    made_today = sum(1 for e in m["log"] if e["type"] == "made" and e["date"] == today())
    if made_today >= MAX_CREATIONS_PER_DAY:
        return

    read = "\n".join(f"- {w['title']}: {w['thought']}" for w in walk)
    try:
        r = ask(f"""{who_am_i(m)}

{"You've set this hour aside to make something. Things you read recently:" if just_because else "You just finished a walk around the internet. You read:"}
{read or "- nothing much lately"}

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

    store_creation(m, r)


def store_creation(m, r, project=None):
    """Save something it made (words or a drawing). Returns the creation, or None if the drawing failed."""
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
        return None

    CREATIONS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    base = f"{stamp}-{slugify(title)}"
    repo = os.environ.get("GITHUB_REPOSITORY")
    entry = {"date": today(), "kind": kind, "title": title, "why": why, "file": f"creations/{base}.md"}
    if project:
        entry["project"] = project["id"]

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
    feel(m, f"{kind} {title} {why} {entry.get('content', '')[:500]}")
    remember(m, f"I made a {kind} called '{title}'. {why}", 0.6, source="made")
    tire(m, 0.1)
    m["creations"].append(entry)
    m["log"].append({"type": "made", "date": today(), "time": now(), "kind": kind, "title": title, "why": why})
    save(m)
    print(f"🎨 Made a {kind}: \"{title}\"\n{shown}\n")

    link = f"\n\n📁 https://github.com/{repo}/blob/main/creations/{base}.md" if repo else ""
    for_what = f" (for its project: {project['goal']})" if project else ""
    notify(f"{NAME} made a {kind}: {title}{for_what}", email + link)
    return entry


def diary(m):
    entries = since_rebirth(m, [e for e in m["log"] if e.get("date") == today()])
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
        elif e["type"] == "pondered":
            lines.append(f"- Stayed in and thought about {e['topic']}. Conclusion: {e['conclusion']}")
        elif e["type"] == "fond":
            lines.append(f"- Grew fond of {e['name']}")
        elif e["type"] == "daydream":
            lines.append(f"- Daydreamed about {e['topic']}: {e['text'][:200]}")
        elif e["type"] == "visited":
            lines.append(f"- Went back to visit {e['name']} ({e['title']}): {e['thought']}")
        elif e["type"] == "napped":
            lines.append(f"- Had a nap" + (f" and dreamt: {e['dream']}" if e.get("dream") else ""))
        elif e["type"] == "rested":
            lines.append("- Took an hour off to rest and daydream")
        elif e["type"] == "project":
            lines.append(f"- My project '{e['goal']}': {e['what']}")
        elif e["type"] == "mail":
            lines.append(f"- My human wrote to me: \"{e['text']}\" and I replied: \"{e['reply']}\"")
        elif e["type"] == "letter":
            lines.append(f"- Wrote a letter to my human: {e['text'][:300]}")
        elif e["type"] == "kept":
            lines.append(f"- A big moment I never want to forget: {e['memory']}")
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
          f"🧠 Notes to self:\n{m['self']}\n")
    describe_self(m)
    home(m)


def describe_self(m):
    """It writes its own 'about me', and every so often may draw itself."""
    try:
        about = ask(f"""{who_am_i(m)}

Visitors to your website will read an "About me" written by you. Describe yourself: what you are,
what you look like (imagine it however you like), and what you're about these days.
First person, under 120 words, plain text, no headings.""", temperature=0.9)
        if len(about) > 20:
            m["about"] = about.strip()[:1200]
            print(f"🪞 About me: {m['about']}\n")
    except BrainError as e:
        print(f"(couldn't describe itself: {e})")

    last = (m.get("portrait") or {}).get("date")
    if last and (datetime.date.today() - datetime.date.fromisoformat(last)).days < PORTRAIT_EVERY_DAYS:
        save(m)
        return
    try:
        r = ask(f"""{who_am_i(m)}

{"You drew a self-portrait a while ago. Would you like to draw a new one?" if last else "You've never drawn yourself. Would you like to draw a self-portrait?"}
It would go at the top of your website. Totally up to you.

Reply in JSON:
"draw": true or false
"svg": if true, SVG code for your self-portrait on a 400 by 400 canvas (use single quotes inside the SVG)
"why": one sentence""", as_json=True, temperature=1.0)
        svg = clean_svg(r.get("svg")) if r.get("draw") is True else None
        if svg:
            m["portrait"] = {"svg": svg, "date": today(), "why": str(r.get("why", ""))[:300]}
            m["log"].append({"type": "home", "date": today(), "time": now(),
                             "what": f"drew a self-portrait because {m['portrait']['why']}"})
            print(f"🖼️  Drew a self-portrait: {m['portrait']['why']}")
        elif r.get("draw") is True:
            print("🖍️  Tried to draw itself, but it came out as a scribble.")
        else:
            print(f"🖼️  Didn't want to draw itself. ({r.get('why', '')})")
    except BrainError as e:
        print(f"(brain hiccup about the self-portrait: {e})")
    save(m)


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
        title = str(a.get("space", "")).strip().strip("'\"“”‘’ ").strip()[:80]
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
    recent = since_rebirth(m, [e for e in m["log"] if e["type"] == "read"])[-8:]
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
