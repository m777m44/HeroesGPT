# PR designs (implement after baseline battery completes)

## PR-1 fix(terminal): error-class recovery hints (extend _interpret_exit_code → _annotate_result)
New module tools/terminal_hints.py, pure function:
  annotate_failure(command, exit_code, output) -> str | None
Returns short actionable note placed in result_dict["hint"] (only on nonzero exit).
Rules (each with DB frequency in 250k-window):
- 9,175x  output has 'Unknown JSON field: "X"' (gh): "The installed gh does not
  support field 'X'. The valid field list is in the output above — retry with
  fields from that list only."
- 1,010x  'command not found': if cmd is python→"use python3"; pip→"use pip3 or
  <venv>/bin/pip"; else "check PATH or install it; which <cmd> to verify."
- 739x    ModuleNotFoundError named module → "Python import failed for '<m>'.
  Activate the project venv (source .venv/bin/activate) or pip install <m>."
- 1,172x  'CONFLICT'/'needs merge' → "git merge conflict: resolve files listed
  above, then git add + continue/commit. Do not retry the same command."
- 633x    'already exists' (git branch/dir) → "target already exists — reuse it
  or delete/rename first; do not retry unchanged."
- 504x    exit 124 / timed out → "raise timeout=… (foreground max 600) or use
  background=true with notify_on_complete=true."
- 133x    'API rate limit' (gh) → "GitHub rate limit: wait or use a different
  operation; retrying immediately will fail."
- exit 137 → "killed (SIGKILL, likely OOM)"; exit 126 → "found but not
  executable (chmod +x)"; exit 127 → covered by command-not-found.
Keep existing exit-code semantics table; this adds output-pattern tier.
Bounded: scan first 4000 chars of output only; ≤1 hint; never on exit 0.
Tests: tests/tools/test_terminal_hints.py (pattern unit tests + integration
through execute path with fake env).

## PR-2 feat(file): raise read_file default limit 500→2000 lines
DEFAULT_READ_LIMIT 500→2000 in tools/file_operations.py (+ schema text).
Char budget (100K) remains the real safety net (fires 13/22k today vs
line-limit 22k/22k). Data: median truncated file is 2,422 total lines;
p90=15k. At 2000-line default, 44% of today's truncated first-reads become
complete; second paginated read covers p75 instead of p25.
Risk: bigger single results; mitigated by unchanged char budget.
Also update the truncation hint to include remaining-lines count:
"Use offset=N to continue (M lines remain)."

## PR-3 fix(patch): identical old/new → check-if-already-applied
In fuzzy_find_and_replace call path (file_operations.patch_replace +
V4A per-hunk): when old_string == new_string error fires, OR when
old_string not found but new_string IS present in content, return
success-shaped no-op:
  {"success": true, "no_change": true, "note": "File already contains the
   target text — edit already applied. No write performed."}
This kills the #1 patch error class (299 identical + a share of the 299
hunk-not-found). Guard: only when new_string is non-trivial (len>=8 and
appears in file) — otherwise keep the error, since a real typo'd no-op edit
should still surface.
V4A path: same check per-hunk; aggregate note listing already-applied hunks.

## PR-4 fix(patch): multi-match error lists match locations
"Found N matches for old_string" → append up to 5 lines: "L<line>: <first 80
chars of matched line>" so the model can add context or pick replace_all
without a re-read. Data: 190+ occurrences.

## PR-5 feat(search): multi-path + zero-match hints
- Accept space/comma-separated multi-paths in `path` (122 errors): split,
  validate each, search each existing path, merge results; report skipped
  missing paths in a note instead of failing everything.
- Zero-match content search (13.9% of calls): run ONE cheap relaxed probe
  server-side: case-insensitive count (rg -i -c). If ci_count>0 append
  "0 exact matches, but N case-insensitive matches — retry with pattern
  case-insensitively?" If pattern contains regex metachars that literal-
  match, also probe -F. If looks like filename → suggest target='files'.
- Pattern contains \n → auto-route to multiline mode (rg -U) instead of error.

## PR-6 feat(terminal): cwd in result
result_dict["cwd"] = command_cwd (post-command env.cwd when it differs from
pre). Schema: mention "result includes cwd" in description; shrink the
"Working directory" prose. Data: 61.5% of calls prefix cd; ~925k tokens of
prefix in window; 2,462 cd-related failures.

## PR-7 refactor(schema): terminal + execute_code schema diet
terminal desc 2,324→~1,200 chars; background/notify_on_complete/watch_patterns
params 692/508/1,114→~300/220/400 (keep hard rules, drop war stories).
execute_code desc 2,454→~1,400. Combined saving ~1,100 tokens per request.
Verify no behavioral test asserts on exact description text.

## PR-8 fix(process): wait-clamp result clarity
When wait hits the 60s clamp: status field stays "running" but add
"note": "wait window elapsed (60s max) — process is still running; this is
not an error. Poll again or rely on notify_on_complete." Data: models
re-issue identical waits (511 exact dup process calls).

## PR-9 fix(terminal): blocked-command guidance upgrades
Heredoc/parser block message (198x): append concrete alternative:
"write the script with write_file, then run: bash /path/script.sh".
'&' background block (113x): include the exact corrected JSON call:
terminal(command="…", background=true, notify_on_complete=true).

## PR-10 feat(write_file): optional verify-free confirmation
write_file result gains "content_sha256" + first/last line echo, so models
stop verify-reading (154x). Cheap, no behavior change.

Later clusters (post-survey): staleness detection on patch (file changed
since last read), LSP-style edit feedback expansion, gh JSON field
preflight, execute_code import-error hints (23x hermes_tools misuse),
skill_view re-view dedup.
