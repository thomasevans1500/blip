# Blip

A small creature that lives on the internet. Every hour it wanders Wikipedia, hopping from link
to link and deciding what it finds interesting. Every night it writes a diary entry and its
personality shifts a little based on what it read.

Its whole mind lives in [`memory.json`](memory.json): traits, interests, everything it read, and its diary.

## How it lives

- **Brain:** [Ollama](https://ollama.com) running `llama3.2:3b`, an open-source model. Free, no API keys.
- **Body:** GitHub Actions ([`.github/workflows/blip.yml`](.github/workflows/blip.yml)) starts a
  machine, installs Ollama, runs Blip, then commits its updated memory back here.
- **Schedule:** wanders hourly at :17, writes its diary at 22:48 (UTC).

## Run it on your own computer

1. Install Ollama, then: `ollama pull llama3.2:3b`
2. `pip install -r requirements.txt`
3. One of:
   - `python creature.py wander` - read a few articles
   - `python creature.py diary` - write today's diary entry
   - `python creature.py chat` - talk to it (`bye` to leave)

Run `git pull` first so you have its latest memory. If you chat locally and want Blip to remember
it, commit and push `memory.json` afterwards.

## Settings (environment variables)

| Variable       | Default                  | What it does                                    |
|----------------|--------------------------|-------------------------------------------------|
| `BLIP_CONTACT` | (empty)                  | Contact URL/email sent to Wikipedia in the User-Agent |
| `BLIP_MODEL`   | `llama3.2:3b`            | Which Ollama model is its brain                 |
| `BLIP_HOPS`    | `5`                      | Articles read per wander                        |
| `OLLAMA_URL`   | `http://localhost:11434` | Where Ollama is running                         |
