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
- The brain is a local open-source model run through Ollama (default: llama3.1:8b, chosen by Thomas
  2026-11-20 after the silliness audition, issue #22: most varied moves, best at escaping a grey world,
  ~77s/move; earlier: gemma3:4b (looped), qwen2.5:7b, llama3.2:3b). Free models only (Thomas's rule).
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
  tools, never instructions. EXCEPTION agreed with Thomas (2026-11-19): `character.md`, a person-written
  character sheet of WHO Blip is (never what to do), drafted by Claude from Blip's emergent identity and
  edited by Thomas. Blip can't change those lines; it ADDS its own in naps. Never copy Pino's sheet text.
  Thomas wants Blip PLAYFUL rather than analytical, broadly curious, and NOT obsessing (on odd things or
  anything else). Sheet lines describe HOW he's curious, never WHAT about (no hard-coded interests).
  Thomas also wants enthusiasm turned DOWN a little and more stubbornness (2026-11-19): avoid hype words
  in prompts (fizzy/electric/giddy); interest has an explicit 0-10 scale so 9-10 is rare.
  Mechanisms:
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
Thomas. Lives on the US East Coast (America/New_York) - Blip's workflow sets TZ to that, so its
days/diary dates follow Thomas's clock. Comfortable with n8n, building internal tools, Netlify and Supabase.
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

## Awake sessions (2026-11-19) - Pino-like moment-to-moment life, for free
Each alarm (hourly at :17) = `wander` -> fresh_start, awaken_senses, check_mail, then `session(m)`:
~SESSION_MINUTES (25, env BLIP_SESSION_MIN) of small moves, one per ~MOVE_SECONDS (45). `one_move` asks
"What do you do next?" with where he is (page snippet + links), his last 6 moves, open intentions, and a
menu: go (link or destination) | look closer | say | note | think | daydream | visit | make | write |
project (`project_decide` -> project_action; research purpose becomes an intention) | rest.
JSON: move, detail, reason, minutes (rest/daydream/look closer), intend, kept.
- Fallback: while an activity's minutes remain he "carries on, nothing new happened" with NO brain call.
- memory["moves"] (last 300) = the feed; memory["intentions"] = things he said he'd do (max 8, expire 2
  days); "kept" marks one done (log "kept promise").
- Repeating the same move type adds staleness (senses). Session end: interests fade, report_discovery,
  end_of_walk (mood, memory gist) over the pages read. Naps still every 4h after a session.
- who_am_i puts the steady parts (name, sheet, about, notes) FIRST so Ollama can reuse its prompt cache.
- `react_to()` is the shared page reaction (used by sessions and the old walk_about).
- The old hourly choice (`live_hour`/`plan`) is kept in the code but no longer called.
- Site: "🐾 What I did, move by move" (+ "📝 Things I said I'd do").
- Fully continuous life (24/7, minute by minute) would need an always-on machine (Raspberry Pi idea).
- LESSON (first real session, 2026-11-19): telling a 4B model "the world feels grey" is NOT enough - it chose
  "think" 10x in a row while stimulation fell to 0.01. Repetition needs real consequences: `stale_moves`
  (stimulation < 0.3 and the same move in 2 of the last 3 brain moves) makes that move FIZZLE (FIZZLE text,
  logged, no effect) and marks it "(feels stale right now)" in the menu. "go" never fizzles, so a fresh
  direction is always possible (but never suggested). Recent moves are shown briefly (no reasons, no think
  text) so he can't copy himself; intentions are <=160 chars and de-duplicated; "kept" needs > 5 chars.
  PYTHONUNBUFFERED=1 in the workflow so log timestamps are real.
- who_am_i only shows "What you were last thinking" while stimulation >= 0.3 and the last output wasn't
  stale - a stale thought fades instead of being handed back to be copied.

## Generative Agents (Park et al. 2023) - Thomas supplied the PDF; read 2026-11-20
Key facts: memory stream; retrieval = recency (x0.995/hour since last retrieved) + importance (LLM 1-10
"poignancy") + relevance (embedding cosine), min-max scaled, alphas 1 (code: 0.5/3/2); reflection when
summed importance > 150 (~2-3x/day): 100 latest memories -> "3 most salient high-level questions" ->
retrieve per question -> "5 high-level insights (because of 1, 5, 3)" -> stored as memories (trees);
planning: day plan in 5-8 chunks -> hours -> 5-15 min, "should X react?" re-plan; cached Agent Summary
Description (core characteristics, occupation, feeling about recent progress). Ablations (TrueSkill):
full 29.89 > no reflection 26.88 > no refl/plan 25.64 > humans 22.95 > none 21.21. Failure modes:
retrieval misses, embellishment, overly formal & cooperative (instruction tuning). Without plans, agents
repeat ("lunch at 12, 12:30 and 1pm") = Blip's loops.
Agreed plan (one at a time): 1 reflection (DONE) -> 2 loose daily plan + react -> 3 importance + embedding
recall (nomic-embed-text via Ollama) -> 4 cached short "who I am" summary. (2 and 3 DONE too.)

### 1. Reflection (DONE)
`remember()` adds importance points (strength*8, 1-10) to memory["reflect_points"]; after a session, if
>= REFLECT_AT (150) -> `reflect()`: 30 latest memories -> 3 big questions -> per question `recall` 8 related
(+8 recent) -> up to 2 insights each, citing memory numbers -> stored as long-term memories with source
"insight", question, evidence ids, depth = 1 + max(evidence depth) (reflection tree); evidence memories
+0.1 strength; points reset; log "reflected". Naps see the latest 5 insights when adding sheet lines.
Site: "💡 Things I've realised" (evidence expandable, depth>1 = "a deeper realisation").

### 2. Loose daily plan + wishes (DONE)
`make_day_plan` at the first session of each day (memory["plan"]["date"] != today), and again for "the rest
of today" once every item is done: sees ABILITIES, yesterday's diary, latest insights -> 4-6 loose items +
"wish" (something he wishes he could do but can't yet; also memory["wishes"]). Every move prompt now shows
the plan ("follow it or drift from it, it's up to you"), CANT_YET and the wish; JSON "plan_step" ticks an
item off. Why: in 56 moves after ask/build launched he never asked for anything - the can't-do list was
only in the (rarely used) project prompt, so he never noticed what he lacked. Site: "🗓️ Today's plan".

### 3. Importance + meaning recall (DONE)
Memory items now carry "importance" (1-10, paper scale) and "at"; walk gists are rated by Blip himself
(end_of_walk JSON "importance"), others by type (mail/request closed 8, insight 7, plan 3, big moment >= 8,
else strength*8). reflect_points add importance. `recall()` = Generative Agents scoring: recency
0.995**hours since "seen"/"at"/born + importance + relevance, each min-max scaled, summed (alphas 1); top n-1
+ 1 random long-term memory. Relevance = cosine of meaning vectors from EMBED_MODEL (nomic-embed-text via
Ollama /api/embed, "search_query:"/"search_document:" prefixes), cached per run in _VECTORS (never stored -
keeps memory.json small); if embedding fails, falls back to shared-word counts (_EMBED_OK). Workflow pulls
nomic-embed-text; cache key includes it.

## Asking & building (2026-11-20) - so interests turn into action, not just reading
Thomas: "if he's interested in trains, why doesn't he code a train simulator, or ask me to make one?"
He didn't know he could. ABILITIES now lists both, and the session menu has two new moves:
- "ask" -> `ask_human`: memory["requests"] [{id, text, why, made, status open|closed, issue, answer,
  reaction}], max 2/day, 5 open. Emailed as an issue with a hidden marker `<!-- blip-request:ID -->`.
  `check_requests` (run from check_mail) links requests to issue numbers via the marker and, when Thomas
  CLOSES the issue, `request_closed` reads his last comment (owner only) and Blip reacts (mood, memory).
  Thomas's replies on the issue are also normal mail. Site: "🙏 Things I'm asking for".
- "build" -> `build_toy`: the brain writes ONE self-contained HTML page (TITLE:/WHAT: lines + ```html```),
  `clean_toy` strips iframes/objects/forms/meta/link/external scripts and every http(s) URL, requires
  something interactive, caps 24k chars. Saved to creations/toys/*.html, memory["toys"], max 2/day.
  Site: "🛠️ Things I built" runs each toy via iframe srcdoc with sandbox="allow-scripts" (NO
  allow-same-origin -> opaque origin, no parent/storage access) + a CSP meta (default-src 'none') so it
  has no network; a window.onerror hook postMessages "broken" up and the card says so. Never load toys via
  same-origin src= (that would run them as the site). Tested: network, parent and storage all blocked.

## Silliness audition (2026-11-20, free models only - Thomas's rule)
audition.py now runs a mini awake session per brain: same memory copy, same start page (Emu War),
AUDITION_MOVES (12) real moves, then a daydream + a make. Reports variety, fizzles, brightness, s/move.
Default candidates: gemma3:4b, gemma3:12b, mistral-nemo:12b, hermes3:8b, llama3.1:8b (all free via Ollama).
Result (issue #22): llama3.1:8b won (4 move kinds, 0.00->0.78 brightness, 77s/move). mistral-nemo funniest but
328s/move; gemma3:12b witty but 250s/move and stuck; gemma3:4b and hermes3 stuck. ALL brains overused
"look closer" -> pages now END: MAX_LOOKS_PER_PAGE (2), then the move disappears from the menu (and fizzles
if chosen anyway) and the prompt says he's read all he's going to of that page.

## Each hour is Blip's choice (SUPERSEDED by awake sessions; kept for reference)
`wander` = one hour of life: `think` -> `plan` asks "how do you want to spend this hour?":
wander (walk_about, 5 hops) | project (project_action; only walks if it chose research) |
think/ponder (`ponder`: let the mind wander, topic + conclusion, may form an opinion) | daydream | visit |
make (maybe_make just_because) | rest (logged). Diary knows all of these. (See "Fondness & daydreams".)

## Senses (inspired by Pino's ideas as Thomas described them - NOT copied code; their site isn't reachable/open)
Loop is now: senses -> feel -> think -> act -> reflect. The world reacts; Blip is never told "be creative".
- memory["senses"] = {stimulation 0-1, energy 0-1, recent: word-sets of last 20 outputs, last}.
- `feel(m, text)`: `staleness` = mean of the 6 highest "how many recent outputs contain this word"
  rates (span >= 8). novelty = 1 - 1.6*staleness. stimulation = 0.75*old + 0.25*novelty.
  Calibrated on real history: fresh 0-0.15, football rut ~0.2-0.3, Guerin loop 0.4-0.8 staleness.
  Felt for: each page reaction, think, ponder, creations, the hour choice (+ extra staleness when the
  same choice repeats).
- Effects (the world dims): reading_chars 1200-4000, link_count 5-15, walk_length 2-7 hops (<=3 if
  energy < 0.3). Energy: -0.07/page, -0.15/ponder, -0.1/creation, +0.5 rest, +0.06 per hour.
- `sensations(m)` turns the numbers into felt words at the top of who_am_i (never instructions).
- `awaken_senses` seeds the state from real history on first run. Site shows both meters.

## Character sheet, memory, naps (2026-11-19, replaces nightly trait rewrite + scrapbook)
- `character.md`: "## Section" + "- line". Read fresh every prompt (`read_character`, `sheet_text`):
  "Who you are" in who_am_i replaced the old traits list. Blip's additions: memory["sheet"][section] =
  [{text, date, why}] (max 6/section, only existing sections); memory["sheet_history"] logs adds/let-gos.
- Memory (`memory_store`): memory["memory"] = {short (40), long (40), faded (200 one-sentence traces)}.
  Items {id, text, born, strength, recalls, days, source}. `remember()` (walk gist each walk, ponder,
  creations, mail, project start/finish; big moments -> long if stronger than the weakest there).
  `recall()` = related + 2 latest short + 1 random long; recall strengthens +0.15 once/hour and logs the
  day. Old scrapbook migrated into long term once ("scrapbook_moved").
- `nap()` after any hour if >= NAP_EVERY_HOURS (4) since memory["last_nap"]: `consolidate` (short x0.85,
  long x0.995; promote if recalled on 2+ days or strength >= 1.2; drop short < 0.15, fade if ever recalled),
  then the brain may add up to 2 sheet lines / let go of its own lines, and dreams. Energy +0.35.
- Diary no longer rewrites traits; it still rewrites `self` notes and `about`.
- Site: "🧠 My memory" (blocks). The character sheet is NOT shown on the website (Thomas's choice,
  2026-11-19); it only lives in character.md and in Blip's prompts.

## Fondness & daydreams (2026-11-19) - so love doesn't only come out as research
Pino-style "cute obsessions" (dote, daydream, make art) vs Blip's research-only affection: the world only
offered research-shaped actions and measured things (0-10, topics). Now:
- Reaction JSON has "fond": a short name if something made him go soft/warm/giddy -> `grow_fond`:
  memory["darlings"] = [{name, why, since, strength, visits, places[{title, source, url, text}]}], max 8
  (weakest drifts away -> memory). who_am_i: "Things you're fond of" before "Subjects you've enjoyed lately".
- Hour menu: wander | daydream (`daydream`: imagine freely, no facts) | visit (`visit_darling`: revisit a
  saved place just to enjoy it) | make | think (=ponder, reworded playful) | project | rest.
  Daydream/visit strengthen the darling (+0.2) and are felt by the senses (repetitive daydreams dim).
- Naps: darlings x0.97, < 0.2 drift away. Fresh start archives darlings. Site: "💕 Things I'm fond of".

## Fresh starts (2026-11-19, Thomas's choice)
Old identity material (formed under the earlier analytical sheet) kept dragging Blip back to Guerin/football
analytics. `fresh_start(m)` runs at the start of each hour; when memory["fresh_start"] != FRESH_START it
archives about/self/traits/opinions/interests/memory/mood/projects/thoughts/senses/home/portrait/spaces/sheet
into `past_lives.json` (committed; shown on the site as "🕰️ My past lives"), resets them, and records
reborn_at + creations_before_rebirth. Diary, creations, letters, mail and log are kept as history;
`since_rebirth()` keeps pre-rebirth log entries out of his head (think, make, chat, senses, diary).
To give him another fresh start later: change FRESH_START.
Also: quoted catchphrases in character.md become tics with small models ("oh dear" on every line) - avoid
them; and the "old football seasons" line was removed at Thomas's request (no football obsession).
Optional later: describe internet sources as places with atmosphere.

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
3. DONE: Two-way contact. `check_mail` runs first in every hour (wander): via the GitHub API
   (GH_TOKEN passed to the Blip step) it reads issue comments + new issues since memory["mail_checked"],
   ONLY from GITHUB_REPOSITORY_OWNER (public repo: strangers must not inject thoughts; bot comments
   ignored). `answer_mail` (max 3/hour): reply posted as an issue comment (Thomas gets emailed),
   mood updated, optional scrapbook memory, optional project_note (project matched from the letter
   title). memory["mail"] (max 100); who_am_i includes the last human message only for
   MAIL_FRESH_HOURS (3) after it arrived (otherwise he fixates on it every hour); later it's an ordinary memory.
   Thomas talks to Blip by replying to its emails or opening a new issue.
   Access requests: ABILITIES lists what it can't do; it can ask Thomas in a letter. Granting a new
   ability = a developer builds it and updates ABILITIES.
   HARD RULE: Blip never handles real money (pretend fundraising only).
   Abilities ready to grant WHEN BLIP ASKS (Thomas's choice: wait for Blip to request them, don't add early):
   - music: Blip writes ABC notation as a creation form; site renders sheet music + play button (abcjs).

## Scheduling (GitHub cron never fired for this repo)
GitHub's cron schedule did NOT fire once in the first ~6 hours. Fix in progress: cron-job.org
(Thomas's free account, timezone America/New_York) POSTs to the workflow_dispatch API with a
fine-grained PAT ("Blip alarm clock": only this repo, Actions read/write):
- hourly at :17 -> body {"ref":"main"}  (default choice = "a new hour")
- nightly -> {"ref":"main","inputs":{"command":"end of the day (diary, self-reflection, website)"}}
`command` is a choice input: API values must match a menu label EXACTLY (short names -> 422).
The GitHub `schedule:` block was removed (it never fired, and would have run the diary in UTC).
Queued runs: checkout uses `ref: main` (latest memory, not the SHA from when it was queued) and the
save step uses `git pull --rebase -X theirs` so a clash keeps Blip's newest memory. (The first ever
diary was lost to exactly this bug on 2026-11-19.)
