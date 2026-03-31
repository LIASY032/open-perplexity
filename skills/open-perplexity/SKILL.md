---
name: open-perplexity
description: Ask the Perplexity web app through the local open-perplexity CLI, reusing a logged-in Chrome session through Chrome DevTools Protocol.
---

# Open Perplexity

Use this skill when the user wants a live Perplexity web answer from the local machine instead of a direct model answer.

Current support scope:

- Linux desktop only
- Requires a visible browser session
- Not for headless Linux servers

## What it does

- Runs the local `open-perplexity` CLI from this repository.
- Reuses a logged-in Chrome or Chromium profile through Chrome DevTools Protocol (CDP).
- Supports optional Perplexity model switching when the web UI exposes it.

## Before first use

Run:

```bash
./skills/open-perplexity/bin/setup
```

This creates `.venv` and installs the package in editable mode.

## Usage

Simple prompt:

```bash
./skills/open-perplexity/bin/open-perplexity --prompt "Summarize today's top AI infrastructure news."
```

Prompt file:

```bash
./skills/open-perplexity/bin/open-perplexity --prompt-file /absolute/path/to/prompt.txt --model claude
```

Pipe from stdin:

```bash
printf 'Explain zero-knowledge proofs in plain English.' | ./skills/open-perplexity/bin/open-perplexity
```

## Notes

- This depends on the current Perplexity web UI, so selectors may need updates if the site changes.
- The first run may copy the local Chrome profile so the logged-in session can be reused.
- Prefer English prompts by default unless the user asks for another language.
