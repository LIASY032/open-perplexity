# Open Perplexity

Open Perplexity is a small plugin-style project that lets people ask the Perplexity website from their own computer.

Technically, it is a Python command-line interface (CLI, a program you run in Terminal) that drives a logged-in Chrome or Chromium browser through Chrome DevTools Protocol (CDP, a browser control interface). It is packaged so it can be used as:

- a normal Python tool,
- a Codex/OpenClaw-friendly plugin project,
- a local skill wrapper inside this repository.

## Why it matters

This project is useful when you want browser-based Perplexity access instead of an official API flow.

Examples:

- Everyday example: ask Perplexity to summarize a long article while reusing your existing browser login.
- Research workflow example: run a saved prompt file from a local script and capture the answer into a markdown note.
- Agent workflow example: let Codex or OpenClaw call a local tool that opens the real Perplexity web app.

## Current platform scope

Right now, this project should be treated as `Linux desktop only`.

That means:

- It is meant for Linux machines with a graphical user interface (GUI, a normal desktop where Chrome can open visibly).
- It is not meant for headless servers (servers without a visible desktop session).
- It is not yet documented or supported as a macOS or Windows tool, even if parts of the code may look portable.

Examples:

- Supported example: Ubuntu Desktop with a logged-in Chrome session.
- Supported example: A Linux workstation with X11 or Wayland and a visible browser window.
- Not supported example: Ubuntu Server running without a desktop environment.

## What is included

- `open-perplexity` CLI for terminal use
- `.codex-plugin/plugin.json` so the repo can behave like a plugin project
- `skills/open-perplexity/` so local agent tools can call it consistently
- English-first docs plus a Chinese guide
- A local `.venv` setup flow

## License choice

This repository uses `MIT` license (a very permissive open-source license). That is a good fit here because:

- it is easy for other people to adopt,
- it is common for small developer tools,
- the repository already used MIT, so keeping it avoids unnecessary legal churn.

If you later want stronger explicit patent language, `Apache-2.0` is another good option. For this repo, MIT is the simplest and safest continuation.

## Quick start

### 1. Create the virtual environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Or use the included helper:

```bash
./skills/open-perplexity/bin/setup
```

### 2. Ask Perplexity

With a direct prompt:

```bash
open-perplexity --prompt "Explain retrieval-augmented generation in simple terms."
```

With a prompt file:

```bash
open-perplexity --prompt-file ./prompt.txt --model claude
```

With standard input (stdin, text piped from another command):

```bash
printf 'List 5 risks of browser automation.' | open-perplexity
```

## How it works

1. It starts Chrome or Chromium with a CDP port if needed.
2. It opens or reuses a Perplexity tab.
3. It puts your prompt into the page input.
4. It submits the prompt and waits for the reply to stabilize.
5. It prints the extracted answer or saves it to a file.

## CLI options

```text
open-perplexity --prompt TEXT
open-perplexity --prompt-file FILE
open-perplexity --model claude
open-perplexity --timeout 120
open-perplexity --cdp-port 9222
open-perplexity --profile-dir ~/.config/google-chrome-cdp
open-perplexity --chrome-path /path/to/chrome
open-perplexity --output-file answer.md
open-perplexity --quiet
```

## Plugin and skill use

Plugin metadata lives at [`/.codex-plugin/plugin.json`](/Users/fanliang/Downloads/open-perplexity/.codex-plugin/plugin.json).

The local skill lives at [`/skills/open-perplexity/SKILL.md`](/Users/fanliang/Downloads/open-perplexity/skills/open-perplexity/SKILL.md).

Examples:

- Plugin-style example: another tool scans this repository and reads `.codex-plugin/plugin.json`.
- Skill-style example: a local Codex workflow runs `./skills/open-perplexity/bin/open-perplexity --prompt "..."`

## Practical notes

- This tool depends on the Perplexity website structure, so selectors may break if the site changes.
- The first run may copy your local Chrome profile to reuse your logged-in session.
- This project does not bypass Perplexity authentication. It uses your own local browser state.
- Treat the current release as Linux desktop only, not as a headless server automation tool.

## Chinese documentation

See [`README.zh-CN.md`](/Users/fanliang/Downloads/open-perplexity/README.zh-CN.md).

## Short recap

Open Perplexity is a reusable, English-first local plugin project for asking the Perplexity website through your own browser session, with both CLI and skill-friendly entry points.
