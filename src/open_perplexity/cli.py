from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DEFAULT_CDP_PORT, DEFAULT_PROFILE_DIR, DEFAULT_TIMEOUT_SECONDS, OpenPerplexityError, RunConfig, run_prompt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-perplexity",
        description="Ask the Perplexity web app through Chrome DevTools Protocol.",
    )
    parser.add_argument("--prompt", help="Prompt text. If omitted, use --prompt-file or stdin.")
    parser.add_argument("--prompt-file", help="Path to a text file containing the prompt.")
    parser.add_argument("--model", help="Optional model switch, for example claude, chatgpt, sonar, gemini, or grok.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Maximum seconds to wait for the answer.")
    parser.add_argument("--cdp-port", type=int, default=DEFAULT_CDP_PORT, help="Chrome remote debugging port.")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="Directory used for the CDP browser profile clone.")
    parser.add_argument("--chrome-path", help="Explicit Chrome or Chromium executable path.")
    parser.add_argument("--output-file", help="Write the answer to a file instead of stdout.")
    parser.add_argument("--quiet", action="store_true", help="Hide progress logs on stderr.")
    return parser


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt.strip()
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise OpenPerplexityError("Provide --prompt, --prompt-file, or stdin.")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        prompt = load_prompt(args)
        config = RunConfig(
            prompt=prompt,
            model=args.model,
            timeout_seconds=args.timeout,
            cdp_port=args.cdp_port,
            profile_dir=Path(args.profile_dir).expanduser(),
            chrome_path=args.chrome_path,
            verbose=not args.quiet,
        )
        result = run_prompt(config)
        if args.output_file:
            Path(args.output_file).write_text(result, encoding="utf-8")
        else:
            print(result)
        return 0
    except OpenPerplexityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
