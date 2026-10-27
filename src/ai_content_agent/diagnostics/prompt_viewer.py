from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOGS_DIR = "logs/prompts"
DEFAULT_OUTPUT = "logs/prompts/index.html"

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Content Agent - Prompt Viewer</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; background: #f6f8fa; color: #24292f; }}
  header {{ padding: 16px 24px; background: #24292f; color: #fff; }}
  header h1 {{ margin: 0; font-size: 18px; }}
  main {{ padding: 16px 24px; max-width: 1100px; margin: 0 auto; }}
  .stats {{ color: #57606a; font-size: 13px; margin-bottom: 12px; }}
  details {{ background: #fff; border: 1px solid #d0d7de; border-radius: 6px; margin-bottom: 8px; }}
  summary {{ cursor: pointer; padding: 10px 14px; font-weight: 600; }}
  summary .meta {{ font-weight: 400; color: #57606a; font-size: 12px; margin-left: 8px; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
  .badge-ok {{ background: #dafbe1; color: #1a7f37; }}
  .badge-err {{ background: #ffebe9; color: #cf222e; }}
  .badge-fb {{ background: #fff8c5; color: #9a6700; }}
  pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
  .empty {{ padding: 40px; text-align: center; color: #57606a; }}
</style>
</head>
<body>
<header><h1>AI Content Agent - Prompt Viewer</h1></header>
<main>
  <p class="stats">{stats} prompts recorded. Generated {generated}.</p>
  {entries}
</main>
</body>
</html>
"""

_ENTRY_TEMPLATE = """<details>
  <summary>{name} <span class="meta">{stamp} &middot; {run_id} &middot; {chars} chars &middot; {elapsed}</span> {badge}</summary>
  <pre>{content}</pre>
</details>
"""


def _stamp_from_filename(filename: str) -> str:
    # Filenames are {YYYYMMDD}_{HHMMSS}_{ffffff}_{run}_{label}.txt
    parts = filename.split("_")
    if len(parts) >= 2:
        token = f"{parts[0]}_{parts[1]}"
        try:
            return datetime.strptime(token, "%Y%m%d_%H%M%S").isoformat(timespec="seconds") + "Z"
        except ValueError:
            pass
    return filename


def _read_metadata(prompt_file: Path) -> dict:
    meta_path = prompt_file.with_suffix(".json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _badge(meta: dict) -> str:
    error = str(meta.get("error") or "")
    if error.startswith("fallback:"):
        return '<span class="badge badge-fb">fallback</span>'
    if meta.get("exit_code") not in (0, None):
        return '<span class="badge badge-err">error</span>'
    return '<span class="badge badge-ok">ok</span>'


def _render_entry(prompt_file: Path) -> str:
    meta = _read_metadata(prompt_file)
    parts = prompt_file.stem.split("_")
    if len(parts) >= 5:
        name = "_".join(parts[4:])
        run_id = parts[3]
    elif len(parts) >= 4:
        name = parts[-1]
        run_id = parts[3]
    else:
        name = prompt_file.stem
        run_id = "no-run"
    stamp = meta.get("created_at", _stamp_from_filename(prompt_file.name))
    chars = meta.get("prompt_chars", prompt_file.stat().st_size)
    elapsed = f"{meta.get('elapsed_seconds', 0.0)}s"
    content = html.escape(prompt_file.read_text(encoding="utf-8"))
    return _ENTRY_TEMPLATE.format(
        name=html.escape(name),
        stamp=html.escape(str(stamp)),
        run_id=html.escape(run_id),
        chars=chars,
        elapsed=html.escape(str(elapsed)),
        badge=_badge(meta),
        content=content,
    )


def generate_html(logs_dir: str | Path = DEFAULT_LOGS_DIR, output: str | Path = DEFAULT_OUTPUT) -> Path:
    logs_dir = Path(logs_dir)
    output_path = Path(output)
    entries_html = ""
    if logs_dir.exists():
        prompt_files = sorted(
            (p for p in logs_dir.glob("*.txt") if p.name != "index.html"),
            key=lambda p: p.name,
            reverse=True,
        )
        entries_html = "\n".join(_render_entry(p) for p in prompt_files)
    if not entries_html:
        entries_html = '<div class="empty">No prompt logs recorded yet.</div>'
        stats_count = 0
    else:
        stats_count = len(entries_html.split("<details>")) - 1
    page = _PAGE_TEMPLATE.format(
        stats=stats_count,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        entries=entries_html,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> int:
    output = generate_html()
    print(f"Prompt viewer generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
