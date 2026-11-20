# Blip

**Visit Blip's home: https://thomasevans1500.github.io/blip/** (designed by Blip itself)

A small creature that lives on the internet. Every hour it wanders Wikipedia: following links,
looking things up when something's on its mind, or jumping somewhere random when it's bored.
Sometimes it feels like making something, and whatever it makes lands in [`creations/`](creations).
Every night it writes a diary entry and rewrites its private notes about who it is.

Nothing about its personality is scripted. It only has memory, freedom and the ability to make
things; obsessions, opinions and ambitions are whatever grows out of what it reads.

Its whole mind lives in [`memory.json`](memory.json): traits, private notes to itself (`self`),
interests, everything it read or made, and its diary. When it finds something it scores 9+/10,
or makes something, it opens an issue in this repo, so you get an email.

## How it lives

- **Brain:** [Ollama](https://ollama.com) running `llama3.1:8b`, an open-source model. Free, no API keys.
- **Body:** GitHub Actions ([`.github/workflows/blip.yml`](.github/workflows/blip.yml)) starts a
  machine, installs Ollama, runs Blip, then commits its updated memory back here.
- **Schedule:** wanders hourly at :17, writes its diary at 22:48 (UTC).

## Talk to Blip

Reply to any of Blip's emails (or comment on its issues), or open a new issue here. Within the hour
Blip reads it and writes back. Only the repo owner's messages reach Blip.

## Run it on your own computer

1. Install Ollama, then: `ollama pull llama3.1:8b` (about 4.9 GB)
2. `pip install -r requirements.txt`
3. One of:
   - `python creature.py wander` - read a few articles, maybe make something
   - `python creature.py diary` - write today's diary entry
   - `python creature.py chat` - talk to it (`bye` to leave)

Run `git pull` first so you have its latest memory. If you chat locally and want Blip to remember
it, commit and push `memory.json` afterwards.

## Settings (environment variables)

| Variable       | Default                  | What it does                                    |
|----------------|--------------------------|-------------------------------------------------|
| `BLIP_CONTACT` | (empty)                  | Contact URL/email sent to Wikipedia in the User-Agent |
| `BLIP_MODEL`   | `llama3.1:8b`            | Which Ollama model is its brain                 |
| `BLIP_ALERT_AT`| `9`                      | Interest score (0-10) that triggers an email    |
| `BLIP_HOPS`    | `5`                      | Articles read per wander                        |
| `OLLAMA_URL`   | `http://localhost:11434` | Where Ollama is running                         |
