"""
A little creature that lives on the internet.
It wanders Wikipedia, decides what it likes, makes things, writes a diary,
keeps private notes about who it is, and you can talk to it.
Runs entirely free using Ollama (on your computer, or on GitHub Actions).

Commands:
    python creature.py wander   -> it reads a few articles, reacts, maybe makes something
    python creature.py diary    -> it writes today's diary entry and updates who it is
    python creature.py chat     -> talk to it (type 'bye' to leave)
"""

import datetime
import json
import os
import random
import re
import sys
import urllib.parse
from pathlib import Path

import requests

# ---- Settings you can change ----
NAME = "Blip"                                            # your creature's name
MODEL = os.environ.get("BLIP_MODEL", "qwen2.5:7b")       # any model you've pulled with Ollama
HOPS_PER_WANDER = int(os.environ.get("BLIP_HOPS", "5"))  # articles it reads each time it wanders
MAX_LOG = 1000                                           # oldest log entries are dropped past this
ALERT_AT = int(os.environ.get("BLIP_ALERT_AT", "9"))     # interest score that counts as "amazing"
MAX_CREATIONS_PER_DAY = 3                                # stops it flooding the creations folder
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
    return datetime.datetime.now().isoformat(timespec="minutes")


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
            "options": {"temperature": temperature}}
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
    return d["title"], d.get("extract", "")


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
        f"**{best['title']}**: {best['thought']}\n\n"
        f"Feeling: {best['feeling']} · Interest: {best['interest']}/10\n\n"
        f"🔗 {wiki_url(best['title'])}"
    )
    notify(f"{NAME} found something: {best['title']}", body)
    print(f"✨ That was amazing! Leaving a note about {best['title']}.")


def choose_next(nxt, options):
    """Turn the model's 'next' answer into an article title (or None for random)."""
    nxt = str(nxt or "").strip()
    if nxt.upper().startswith("SEARCH"):
        query = nxt.split(":", 1)[1].strip() if ":" in nxt else ""
        if query:
            found = search(query)
            print(f"🔎 searching for \"{query}\" -> {found or 'nothing found'}")
            return found, f"searched for '{query}'"
        return None, "jumped somewhere random"
    for o in options:
        if nxt.lower() == o.lower():
            return o, "followed a link"
    return None, "jumped somewhere random"


def wander(m):
    title = m.get("current")
    best = None
    walk = []        # what it has read on this walk, so it can notice patterns and get bored
    via = "woke up here"
    for _ in range(HOPS_PER_WANDER):
        try:
            title, text = read_article(title)
            options = get_links(title)
        except (requests.RequestException, KeyError, ValueError):
            print("(got lost, jumping somewhere random)")
            title, via = None, "got lost"
            continue

        so_far = "\n".join(f"- {w['title']} ({w['feeling']}, {w['interest']}/10)" for w in walk) or "- nothing yet, you just set off"
        prompt = f"""{who_am_i(m)}

On this walk so far you've read:
{so_far}

You just read this article ({via}).
TITLE: {title}
TEXT: {text[:1500]}

Links you could follow next: {json.dumps(options)}

Reply in JSON with these keys:
"thought": one or two sentences of your honest reaction, in your own voice
"feeling": one word
"interest": a number from 0 to 10 for how much this grabbed you
"topics": a list of 1 to 3 short topic words this article is about
"next": where you go next. Either copy one link exactly from the list,
        or "SEARCH: <anything>" to go and look up whatever you want,
        or "RANDOM" to jump somewhere completely new"""

        try:
            r = ask(prompt, as_json=True)
        except BrainError as e:
            print(f"(brain hiccup: {e})")
            title, via = None, "had a brain hiccup and ended up somewhere random"
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
                 "thought": thought, "feeling": feeling, "interest": interest, "via": via}
        m["log"].append(entry)
        walk.append(entry)
        print(f"📖 {title}\n   {thought} ({feeling}, {interest}/10)\n")
        if best is None or interest > best["interest"]:
            best = entry

        title, via = choose_next(r.get("next"), options)
        m["current"] = title
        save(m)

    report_discovery(best)
    if walk:
        maybe_make(m, walk)


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "untitled"


def maybe_make(m, walk):
    """Ask whether it feels like making something. What and how is entirely up to it."""
    made_today = sum(1 for e in m["log"] if e["type"] == "made" and e["date"] == today())
    if made_today >= MAX_CREATIONS_PER_DAY:
        return

    read = "\n".join(f"- {w['title']}: {w['thought']}" for w in walk)
    try:
        r = ask(f"""{who_am_i(m)}

You just finished a walk around the internet. You read:
{read}

You're free to make something if you genuinely feel the urge. It can be anything at all,
in any form you like. Most walks you won't feel like it, and that's fine.

Reply in JSON:
"make": true or false
"kind": if true, one or two words for what it is (in your own words)
"title": if true, its title
"content": if true, the thing itself (text only; use plain characters if you draw)
"why": one sentence on why you did or didn't feel like making something""", as_json=True, temperature=1.0)
    except BrainError as e:
        print(f"(brain hiccup while thinking about making something: {e})")
        return

    if r.get("make") is not True or not str(r.get("content", "")).strip():
        print(f"🎨 Didn't feel like making anything. ({r.get('why', '')})")
        return

    kind = str(r.get("kind", "thing")).strip() or "thing"
    title = str(r.get("title", "Untitled")).strip() or "Untitled"
    content = str(r["content"]).strip()
    CREATIONS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    path = CREATIONS_DIR / f"{stamp}-{slugify(title)}.md"
    path.write_text(
        f"# {title}\n\n*A {kind} by {NAME}, {today()}*\n\n> {r.get('why', '')}\n\n```\n{content}\n```\n",
        encoding="utf-8")
    m["creations"].append({"date": today(), "kind": kind, "title": title,
                           "file": f"creations/{path.name}"})
    m["log"].append({"type": "made", "date": today(), "time": now(),
                     "kind": kind, "title": title, "why": str(r.get("why", ""))})
    save(m)
    print(f"🎨 Made a {kind}: \"{title}\"\n{content}\n")

    repo = os.environ.get("GITHUB_REPOSITORY")
    link = f"\n\n📁 https://github.com/{repo}/blob/main/creations/{path.name}" if repo else ""
    notify(f"{NAME} made a {kind}: {title}",
           f"*{r.get('why', '')}*\n\n````\n{content}\n````{link}")


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
        else:
            lines.append(f"- Chatted with my human. They said: {e['you']} / I said: {e['me']}")
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
          f"Personality now: {', '.join(m['traits'])}\n\n🧠 Notes to self:\n{m['self']}")


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
    actions = {"wander": wander, "diary": diary, "chat": chat}
    if command in actions:
        actions[command](memory)
    else:
        print("Use: python creature.py wander | diary | chat")
