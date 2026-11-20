"""
Silliness audition: let a different (free, open-source) brain be Blip for a short awake session,
without touching Blip's real memory.

Each candidate gets the same copy of Blip's memory, starts on the same page, and plays BRAIN_MOVES moves of
a real awake session (real internet), then daydreams and maybe makes something. The results show how
playful each brain is and whether it gets stuck repeating itself. Output: audition-<model>.md

    BLIP_MODEL=gemma3:12b python audition.py
"""

import copy
import os
import tempfile
import time
from pathlib import Path

import creature as c

MODEL = c.MODEL
BRAIN_MOVES = int(os.environ.get("AUDITION_MOVES", "12"))
START_PAGE = "Emu War"                     # the same starting place for every brain

# Nothing in an audition is saved, emailed, posted or redecorated
c.save = lambda m: None
c.notify = lambda title, body: None
c.home = lambda m: None
c._github = lambda *a, **k: None
c.CREATIONS_DIR = Path(tempfile.mkdtemp())
c.MOVE_SECONDS = 0

memory = copy.deepcopy(c.load())
c.fresh_start(memory)                      # in case the real Blip hasn't had his fresh start yet
c.awaken_senses(memory)
memory["current"] = START_PAGE
memory["moves"] = []
start_stim = c.senses(memory)["stimulation"]

st = {"place": None, "offset": 0, "activity": None, "left": 0, "reads": [], "purpose": None, "via": "woke up"}
try:
    st["place"] = c.visit_wiki(START_PAGE)
except Exception:
    st["place"] = None

out = [f"## 🧠 `{MODEL}`\n"]
log_from = len(memory["log"])
timings = []
brain_moves = 0
while brain_moves < BRAIN_MOVES:
    if st["left"] > 0:                      # carrying on with something: no brain needed
        st["left"] -= 1
        c.log_move(memory, st["activity"], reason="carried on, nothing new happened", fallback=True)
        continue
    t = time.time()
    try:
        c.one_move(memory, st)
    except Exception as e:                   # one bad move shouldn't end the audition
        out.append(f"⚠️ {type(e).__name__}: {e}\n")
    timings.append(time.time() - t)
    brain_moves += 1

moves = [x for x in memory["moves"] if not x["fallback"] or "stale" in x["reason"] or "circles" in x["reason"]]
kinds = [x["move"] for x in memory["moves"] if not x["fallback"]]
fizzles = sum(1 for x in memory["moves"] if x["fallback"] and x["reason"] in c.FIZZLE.values())
out.append(f"**Variety:** {len(set(kinds))} different kinds of move out of {len(kinds)} · "
           f"**fizzled (stale):** {fizzles} · **world brightness:** {start_stim:.2f} → "
           f"{c.senses(memory)['stimulation']:.2f} · **~{sum(timings) / max(1, len(timings)):.0f}s per move**\n")

out.append("\n**The session, move by move**\n")
for x in memory["moves"]:
    if x["fallback"]:
        out.append(f"- _{x['move']}: {x['reason']}_")
    else:
        out.append(f"- **{x['move']}**{': ' + x['detail'][:160] if x['detail'] else ''}"
                   f"{'  — because “' + x['reason'][:160] + '”' if x['reason'] else ''}")

new = memory["log"][log_from:]
said = [e["text"] for e in new if e["type"] == "said"]
reads = [e for e in new if e["type"] == "read"]
thoughts = [t["text"] for t in memory.get("thoughts", [])[-3:]]
if reads:
    out.append("\n**What he thought of pages**")
    out += [f"> **{e['title']}** ({e['feeling']}, {e['interest']}/10): {e['thought']}" for e in reads[:5]]
if said:
    out.append("\n**Things he said out loud**")
    out += [f"> “{x}”" for x in said[:5]]

# A daydream and a chance to make something, so every brain gets the same creative prompts
d = max(c.darlings(memory), key=lambda x: x["strength"]) if c.darlings(memory) else None
try:
    c.daydream(memory, d)
    dd = [t for t in memory.get("thoughts", []) if t.get("kind") == "daydream"]
    if dd:
        out.append(f"\n**Daydream about {dd[-1]['topic']}**\n> {dd[-1]['text']}")
except Exception as e:
    out.append(f"\n⚠️ daydream: {e}")
before = len(memory["creations"])
try:
    memory["log"] = [e for e in memory["log"] if e["type"] != "made"]   # today's cap shouldn't block it
    c.maybe_make(memory, reads[-5:] or [{"title": START_PAGE, "thought": ""}], just_because=True)
except Exception as e:
    out.append(f"\n⚠️ make: {e}")
if len(memory["creations"]) > before:
    made = memory["creations"][-1]
    body = "(a drawing)" if made.get("svg") else made.get("content", "")[:1200]
    out.append(f"\n**Made a {made['kind']}: _{made['title']}_**\n````\n{body}\n````")
else:
    out.append("\n_Didn't feel like making anything._")
if thoughts:
    out.append("\n**Thinking out loud (latest)**\n> " + thoughts[-1][:600])

name = "audition-" + MODEL.replace(":", "-").replace("/", "-") + ".md"
Path(name).write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
