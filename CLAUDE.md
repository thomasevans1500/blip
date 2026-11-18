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
- The brain is a local open-source model run through Ollama (default: gemma3:4b, chosen by Thomas after the brain
  audition (issue #8) for the liveliest voice and fastest runs; earlier: qwen2.5:7b, llama3.2:3b).
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
- Topic scores go up or down by (interest - 5), and ALL scores fade by INTEREST_FADE (0.99) per wander
  (~20%/day), so obsessions it keeps feeding survive and stale ones fade (stops football-forever ruts).
- It reads the full article plain text (prop=extracts), not just the summary, up to READ_CHARS (4000).
  num_ctx is set to 8192: Ollama's default context is small and silently cuts the start of the prompt
  (which is where its personality lives).
- Prompt wording matters a lot with small models: never add discouraging lines like "most of the
  time you won't..." - the model obeys them literally. Present choices as an equal menu.
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
    It chooses the form: "words" (text/ASCII) or "drawing" (it writes SVG itself, 400x400).
    `clean_svg` allowlists drawing tags and strips scripts/links/external refs; unparseable SVG is
    logged as a "failed drawing" (no file). Drawings saved as creations/*.svg + .md, kept in memory
    ("svg") and shown on the site as <img> data URIs. No image-generation model (Thomas chose
    Blip's own hand over an AI paintbrush).
    Workflow saves/pushes memory BEFORE opening issues so the email's image link already exists.
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

## Personality roadmap (agreed with Thomas, in order)
1. DONE: Brain audition (winner gemma3:4b; hermes3 didn't run due to a registry 503) - `audition.py` + `.github/workflows/audition.yml` (manual): each candidate model
   plays Blip on its real memory (nothing saved; save/notify/home patched out), reacts to the same
   3 places (Emu War, Tardigrade, BBC news), tries to make something, writes a diary. Results -> one
   GitHub issue. Thomas picks the liveliest voice; switch via BLIP_MODEL in blip.yml.
2. DONE: Scrapbook + mood. `end_of_walk` (after report_discovery, before maybe_make) asks how it
   feels now given how it set off -> memory["mood"] {feeling, why, since}; and whether to keep a
   memory in its own words -> memory["scrapbook"] (max 300). `who_am_i(m, context)` includes the
   mood and `recall()`: memories sharing 2+ words (4+ letters) with what it's looking at, the 2
   latest, and 1 random old one (for surprise callbacks). Site shows mood + scrapbook.
3. DONE (merged into "inner life" step 1 below).

## Inner life roadmap (Thomas wants Pino-like agency, but emergent; agreed 3 steps)
1. DONE: Inner voice + opinions + about me.
   - `think(m)` runs at the start of every `wander`: free-text talking-to-itself -> memory["thoughts"]
     (max 200); the latest thought is in who_am_i.
   - Reaction JSON has optional "opinion": {about, opinion} -> memory["opinions"] keyed by lowercased
     about (max 100, counts mind changes). `relevant_opinions()` puts related + recent ones in who_am_i.
   - Nightly `describe_self` (after diary, before home): rewrites memory["about"]; every 7 days it's
     offered to draw a self-portrait (SVG via clean_svg) -> memory["portrait"], shown in the site header.
2. DONE: Wishes, plans & projects. `plan(m)` runs right after `think` in every wander. It sees
   ABILITIES (what it can and can't do - incl. no money) and its projects, then picks ONE action:
   start (goal/why/2-6 steps; max 3 active) | work (how: research / make / update page / write to my
   human) | finish | give up | none. research returns a purpose: the walk starts with SEARCH topic,
   reaction_prompt mentions the purpose (it may still get distracted), and end_of_walk asks for
   project_note + step_done. make -> make_for_project -> store_creation(project=...) (cap 3+2/day).
   write -> write_to_human (notify; max 2/day; log type "letter"). memory["projects"] items:
   {id, goal, why, steps[{text,done}], status active|finished|abandoned, started, updated, log[]}.
   Site: "🎯 What I'm working on" with progress bar, steps, project creations, progress diary.
3. NEXT: Two-way contact + access requests: Blip already emails Thomas (letters); now it should read his replies
   (issue comments) next run. Blip should know its abilities list and can ASK Thomas for abilities
   it lacks (e.g. music, videos); Thomas decides and a developer builds them.
   HARD RULE: Blip never handles real money (pretend fundraising only).
