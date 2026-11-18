# Internet Creature (working name: Blip)

## What this project is
A small autonomous AI creature that lives on the internet. It wanders Wikipedia on its own,
decides what it finds interesting, slowly develops its own tastes and personality, writes a
diary every day about what it found, and can be chatted with.

Inspired by Pino (pinos.world), an autonomous AI bird in a 3D town, but this is NOT meant to
be a copy. No bird, no 3D town. The core idea here is a funny, curious internet-surfer whose
personality grows out of what it reads.

## Hard constraints
- Must be free to run. No paid APIs (no Claude/OpenAI API calls).
- The brain is a local open-source model run through Ollama (default: qwen2.5:7b; was llama3.2:3b).
- The "internet" is currently Wikipedia via its free public APIs (no key needed).
  Always send a descriptive User-Agent header to Wikipedia.

## Current state
Repo: github.com/thomasevans1500/blip (public). `creature.py`, Python + `requests` only.
Runs on GitHub Actions (`.github/workflows/blip.yml`): installs Ollama on the runner, caches the
model, runs `wander` hourly (:17 UTC) and `diary` nightly (22:48 UTC), then commits `memory.json`.
Can also be triggered by hand (Actions tab -> Run workflow). Chat is local-only for now.
Settings come from env vars: BLIP_CONTACT (repo variable, used in the Wikipedia User-Agent),
BLIP_MODEL, BLIP_HOPS, BLIP_ALERT_AT, OLLAMA_URL.

Commands:
- `python creature.py wander` - reads 5 Wikipedia articles, hopping link to link, reacting to each
- `python creature.py diary` - writes today's diary entry, rewrites traits + self-notes, then runs `home`
- `python creature.py home` - redecorates its website and tends its spaces
- `python creature.py chat` - talk to it in the terminal; chats are logged and feed into the diary

How it works:
- `memory.json` (created next to the script) holds everything: traits, interest scores,
  a log of everything it read or said, diary entries, and the article it was last on.
- After each article the model returns JSON: thought, feeling, interest (0-10), topics, next link.
- Topic scores go up or down by (interest - 5), so likes snowball over time.
- Its top interests and traits are fed into every prompt, so it "remembers who it is".
- Personality must EMERGE, not be scripted (Thomas's explicit wish). We give it memory, freedom and
  tools, never pre-written quirks/obsessions/goals. Mechanisms:
  - `self`: free-form private notes it rewrites nightly in `diary`; fed into every prompt via who_am_i.
  - Wander "next" can be a Wikipedia link or any entry in DESTINATIONS: SEARCH/WORD/ASK/BOOKS/SPACE
    (need a topic) or NEWS/HACKER NEWS/ON THIS DAY/RANDOM. Sources: Wikipedia, Wiktionary REST,
    DuckDuckGo Instant Answer, Open Library search, NASA images API, BBC RSS, HN Firebase API,
    Wikipedia on-this-day feed - all free, no keys. Each visit_* returns a place() dict; None = found
    nothing (falls back to random). `python creature.py check` tests every source.
    It sees what it read earlier on the same walk, so it can get bored or chase an obsession.
  - After each wander, `maybe_make` asks open-endedly if it wants to make anything (any form).
    Saved to `creations/*.md`, listed in memory["creations"], capped at 3/day.
- Website, decided by Blip (runs nightly at the end of `diary`, or alone via `home` command):
  - `decorate`: it picks home name, tagline, emoji, bg/text/accent hex, any Google Font -> memory["home"].
    `readable()` only nudges colours to meet contrast; never overrides its taste otherwise.
  - `tend_spaces`: up to 2 actions/night: open / add / close its own "spaces" (rooms on the site)
    -> memory["spaces"]; max 8 open; closed ones are archived, not deleted.
- Alerts: `notify()` queues notes in notify.json (gitignored); the workflow turns each into a
  GitHub issue, which emails Thomas. Sent for: best find of a wander if interest >= BLIP_ALERT_AT (9),
  and every creation (full content + link to the file).
- Small local models sometimes return bad JSON or wrong types; the script skips/normalises
  rather than crashing. Diary is one entry per day (re-running replaces it). Log is capped at 1000.

## About the developer
Thomas. Comfortable with n8n, building internal tools, Netlify and Supabase.
Prefers complete, ready-to-use code and step-by-step instructions, one step at a time,
so he can flag anything confusing before moving on.

## Ideas for next steps
1. ~~Run it on a schedule~~ - done via GitHub Actions.
2. ~~Website~~ - done: `index.html` at repo root, served by GitHub Pages
   (thomasevans1500.github.io/blip). Static page fetches memory.json and renders it; never needs a
   rebuild. All Blip text is rendered as text (no HTML from the model, ever).
3. Let visitors leave it things or talk to it (needs moderation).
- Later: a "boredom" nudge was considered but NOT coded - it can choose RANDOM/SEARCH itself now.
4. ~~Widen its internet~~ - done. Google search is NOT an option: Google's Custom Search API is
   closed to new users (shuts 2027-01-01); Brave needs a credit card. Instead: key-free sources.
5. Possibly move it to a Raspberry Pi 5 to run 24/7.
