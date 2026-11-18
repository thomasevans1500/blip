"""
A little creature that lives on the internet.
It wanders Wikipedia, decides what it likes, writes a diary, and you can talk to it.
Runs entirely free using Ollama (on your computer, or on GitHub Actions).

Commands:
    python creature.py wander   -> it reads a few articles and reacts
    python creature.py diary    -> it writes today's diary entry and its personality updates
    python creature.py chat     -> talk to it (type 'bye' to leave)
"""

import datetime
import json
import os
import random
import sys
import urllib.parse
from pathlib import Path

import requests

# ---- Settings you can change ----
NAME = "Blip"                                            # your creature's name
MODEL = os.environ.get("BLIP_MODEL", "llama3.2:3b")      # any model you've pulled with Ollama
HOPS_PER_WANDER = int(os.environ.get("BLIP_HOPS", "5"))  # articles it reads each time it wanders
MAX_LOG = 1000                                           # oldest log entries are dropped past this
# ---------------------------------

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
WIKI = "https://en.wikipedia.org"
# Wikipedia asks bots to include a way to contact the owner (a URL or email).
# Set BLIP_CONTACT (locally, or as a GitHub repository variable) to e.g. your repo's URL.
CONTACT = os.environ.get("BLIP_CONTACT", "").strip()
HEADERS = {"User-Agent": f"BlipCreature/0.2 ({CONTACT + '; ' if CONTACT else ''}personal hobby project)"}
MEMORY_FILE = Path(__file__).with_name("memory.json")

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
        "interests": {},
        "log": [],
        "diary": [],
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
    top = sorted(m["interests"].items(), key=lambda x: -x[1])[:8]
    loves = ", ".join(t for t, s in top if s > 0) or "nothing yet, you are brand new to the internet"
    return (
        f"You are {NAME}, a small creature who lives on the internet and wanders Wikipedia. "
        f"Your personality: {', '.join(m['traits'])}. "
        f"Things you've grown to love: {loves}."
    )


# ---------- Brain (local model via Ollama) ----------

def _post(path, body):
    try:
        r = requests.post(f"{OLLAMA}{path}", json=body, timeout=600)
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        raise BrainError(f"can't reach Ollama at {OLLAMA} - is it running? (try: ollama serve)")
    except (requests.RequestException, ValueError) as e:
        raise BrainError(str(e))


def ask(prompt, as_json=False):
    body = {"model": MODEL, "prompt": prompt, "stream": False}
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
    params = {
        "action": "query", "titles": title, "prop": "links",
        "plnamespace": 0, "pllimit": "max", "format": "json",
    }
    r = requests.get(f"{WIKI}/w/api.php", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    pages = r.json()["query"]["pages"]
    found = [link["title"] for p in pages.values() for link in p.get("links", [])]
    return random.sample(found, min(15, len(found)))


# ---------- Things it does ----------

def wander(m):
    title = m.get("current")
    for _ in range(HOPS_PER_WANDER):
        try:
            title, text = read_article(title)
            options = get_links(title)
        except (requests.RequestException, KeyError, ValueError):
            print("(got lost, jumping somewhere random)")
            title = None
            continue

        prompt = f"""{who_am_i(m)}
You just read this article.
TITLE: {title}
TEXT: {text[:1500]}

Links you could follow next: {json.dumps(options)}

Reply in JSON with these keys:
"thought": one or two sentences of your honest reaction, in your own voice
"feeling": one word
"interest": a number from 0 to 10 for how much this grabbed you
"topics": a list of 1 to 3 short topic words this article is about
"next": copy one link exactly from the list, or "RANDOM" if none appeal"""

        try:
            r = ask(prompt, as_json=True)
        except BrainError as e:
            print(f"(brain hiccup: {e})")
            title = None
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
        m["log"].append({"type": "read", "date": today(), "time": now(),
                         "title": title, "thought": thought, "feeling": feeling,
                         "interest": interest})
        print(f"📖 {title}\n   {thought} ({feeling}, {interest}/10)\n")

        nxt = r.get("next")
        title = nxt if nxt in options else None
        m["current"] = title
        save(m)


def diary(m):
    entries = [e for e in m["log"] if e.get("date") == today()]
    if not entries:
        print("Nothing has happened today yet. Run 'wander' first.")
        return

    lines = []
    for e in entries:
        if e["type"] == "read":
            lines.append(f"- Read about {e['title']}: {e['thought']} (felt {e['feeling']})")
        else:
            lines.append(f"- Chatted with my human. They said: {e['you']} / I said: {e['me']}")
    events = "\n".join(lines[-40:])

    try:
        text = ask(f"""{who_am_i(m)}
Here is everything that happened to you today:
{events}

Write today's diary entry in first person, in your own voice, 150 to 250 words.
Mention what you found, what you liked or didn't, and any new obsessions. No headings.""")
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

    save(m)
    print(f"📔 {NAME}'s diary, {today()}\n\n{text}\n\nPersonality now: {', '.join(m['traits'])}")


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
and bring up things you've read when it fits."""
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
