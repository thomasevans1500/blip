"""
Brain audition: let a different model "be" Blip for a moment, without touching Blip's real memory.

Each candidate brain gets Blip's real personality and memories, reacts to the same three places,
decides whether to make something, and writes a diary entry. Results go to audition-<model>.md
so the brains can be compared side by side.

    BLIP_MODEL=llama3.1:8b python audition.py
"""

import copy
import json
import os
import tempfile
import time
from pathlib import Path

import creature as c

MODEL = c.MODEL
PLACES = [  # the same for every brain, so it's a fair comparison
    ("an odd bit of history", lambda: c.visit_wiki("Emu War")),
    ("a strange animal", lambda: c.visit_wiki("Tardigrade")),
    ("today's news", c.visit_news),
]

# Nothing in an audition is saved or emailed
c.save = lambda m: None
c.notify = lambda title, body: None
c.home = lambda m: None
c.CREATIONS_DIR = Path(tempfile.mkdtemp())

memory = copy.deepcopy(c.load())
out = [f"## 🧠 `{MODEL}`\n"]
started = time.time()

# 1. Reactions to the same three places
walk = []
via = "woke up here"
out.append("**Reactions**\n")
for label, go in PLACES:
    try:
        p = go()
        t = time.time()
        r = c.ask(c.reaction_prompt(memory, walk, via, p), as_json=True)
        secs = time.time() - t
    except Exception as e:
        out.append(f"- *{label}*: ⚠️ {type(e).__name__}: {e}\n")
        continue
    walk.append({"title": p["title"], "thought": str(r.get("thought", "")),
                 "feeling": str(r.get("feeling", "")), "interest": r.get("interest", "?")})
    out.append(f"- **{p['title']}** ({r.get('feeling', '?')}, {r.get('interest', '?')}/10, {secs:.0f}s)\n"
               f"  > {r.get('thought', '')}\n"
               f"  → next: `{r.get('next', '')}`\n")
    via = "followed its curiosity"

# 2. Does it want to make something?
out.append("\n**Making something**\n")
before = len(memory["creations"])
memory["log"] = [e for e in memory["log"] if e["type"] != "made"]   # don't let today's cap block it
try:
    c.maybe_make(memory, walk)
except Exception as e:
    out.append(f"⚠️ {type(e).__name__}: {e}\n")
if len(memory["creations"]) > before:
    made = memory["creations"][-1]
    out.append(f"Made a **{made['kind']}** called *{made['title']}*. Why: {made['why']}\n")
    if made.get("svg"):
        out.append(f"(a drawing, {len(made['svg'])} characters of SVG; saved in the run's files)\n")
    else:
        out.append("\n````\n" + made.get("content", "")[:1500] + "\n````\n")
elif memory["log"] and memory["log"][-1].get("kind") == "failed drawing":
    out.append(f"Tried to draw *{memory['log'][-1]['title']}* but it came out as a scribble.\n")
else:
    out.append("Didn't feel like making anything.\n")

# 3. A diary entry, written from Blip's most recent real day
out.append("\n**Diary**\n")
days = sorted({e["date"] for e in memory["log"] if e.get("date")})
if days:
    c.today = lambda: days[-1]
    try:
        c.diary(memory)
        out.append("\n".join("> " + line for line in memory["diary"][-1]["entry"].splitlines()) + "\n")
        out.append(f"\n**Its traits after:** {', '.join(memory['traits'])}\n")
        out.append("\n**Notes to self:**\n" + "\n".join("> " + l for l in memory["self"].splitlines()) + "\n")
    except Exception as e:
        out.append(f"⚠️ {type(e).__name__}: {e}\n")

out.append(f"\n*Total time: {(time.time() - started) / 60:.1f} minutes*\n")

name = "audition-" + MODEL.replace(":", "-").replace("/", "-") + ".md"
Path(name).write_text("\n".join(out), encoding="utf-8")
for f in c.CREATIONS_DIR.glob("*.svg"):
    (Path(name).with_suffix(".svg")).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
print("\n".join(out))
