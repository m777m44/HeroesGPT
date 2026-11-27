# Hermes Core Tool Performance — Improvement Candidates (draft, data-driven)

Data sources: state.db mining (1.53M messages, 400k-msg recent window), schema
token audit, code inspection. Baseline benchmark (8 tasks x 3 reps) running.

## Measured pain points

| # | Signal | Magnitude (recent 400k-msg window) |
|---|--------|-------------------------------------|
| P1 | `cd X && ...` prefixes on terminal calls | 60.2% of 104k terminal calls; ~925k tokens of pure prefix; 2,462 failed calls led by `cd` |
| P2 | read_file truncation | 74.3% of 28.5k reads truncated; 12,229 extra re-reads; after truncation the model's next move is terminal (cat/sed) 4,608 times — tool distrust |
| P3 | terminal retry-after-error | 3,697 same-tool retries after failed result |
| P4 | gh `Unknown JSON field` | 9,175 failures in 250k window (gh version drift vs model knowledge) |
| P5 | `python: command not found` | 837+99 (ubuntu has only python3); plus 739 ModuleNotFoundError (venv confusion) |
| P6 | patch identical old/new | 299 identical + 190 multi-match + 299 hunk-not-found; 622 success_false |
| P7 | search_files zero-match | 13.9% of 19.6k searches return 0 matches (silent dead turn); 122 errors from multi-path in one string |
| P8 | process wait/poll churn | 511 exact-duplicate process calls; wait dominates (1,536); poll+wait+log ≈ 2k turns |
| P9 | skill_view volume | 30M tokens in window (5,255 views); no dedup on re-view |
| P10 | timeouts | terminal timeout notes 6.7%; 104 'Command timed out' on cd-chains |
| P11 | exact duplicate consecutive calls | terminal 263, execute_code 227, patch 77, write 15 |
| P12 | write→read same path verify | 154 wasted verify reads (write_file already confirms) |
| P13 | heredoc/parser blocks | 198 BLOCKED parser-limit + 87 nohup-wrapper + 113 '&' backgrounding blocks |
| P14 | schema bloat | 88 tools = ~33k tokens schemas; terminal 1,410 tok; watch_patterns param alone 1,114 chars; execute_code desc 2,454 chars |

## Candidate improvements (each → own PR, benchmarked)

### Cluster A: terminal result enrichment (kill wasted diagnosis turns)
A1. Return `cwd` in terminal result whenever it changed during the call (and
    on every call — cheap, 1 short field). Models prefix `cd` because they
    can't see state. Combined with a schema note "result includes cwd", aims
    to cut the 60% cd-prefix habit AND the `pwd && ls` diagnostic turns.
A2. Expand `_interpret_exit_code` into a general error-pattern annotator:
    - `python: command not found` → note: "use python3 (or the venv's bin/python)"
    - `ModuleNotFoundError: X` → note: "check venv activation; pip install X or activate .venv"
    - `command not found` generic → nearest-command suggestion (PATH scan)
    - exit 124/137 → timeout/OOM-kill note
    - `gh: Unknown JSON field` → note "field list in output; use exactly those"
    - merge-conflict / branch-exists → short next-step note
A3. exit_code 130 [Command interrupted] → explicit note (user interrupt, do not retry).

### Cluster B: read_file pagination trust
B1. Truncated read currently gives next_offset but models flee to terminal.
    Change truncation footer to include the REMAINING line count and a
    stronger continuation contract; consider auto-bumping the char cap when
    limit<=500 requested lines but cap hit early.
B2. `read_file` when limit hits: if the file is only slightly over
    (<=20% over cap), just return the whole thing (avoid a whole second turn
    for 10 lines).
B3. Re-read dedup already exists (skip-identical-reread guard) — verify it
    fires; 12k extra rereads suggest gaps (offset-differing reads are fine).

### Cluster C: patch ergonomics
C1. 'old_string and new_string are identical' (299+) — most common patch
    error. Usually model intent = "ensure state" (edit already applied).
    Return a distinct result: check whether new_string already present in
    file; if yes return success-noop "file already contains the target text
    (no change needed)" instead of error. Saves the re-read + re-patch turns.
C2. Multi-match error: include the N match line numbers + surrounding 1-line
    context so the model can immediately disambiguate (currently just count).
C3. hunk-not-found in V4A: fall back cross-mode — suggest replace-mode with
    closest-match hint (find_closest_lines already exists; wire it into V4A path).

### Cluster D: search_files
D1. Zero-match results (13.9%): append auto-hints — try case-insensitive
    variant result count, nearby pattern relaxation (e.g. drop anchors),
    or if target=content and pattern looks like a filename, suggest target=files.
    Cheap: run the relaxed query server-side and report its count.
D2. Multi-path support or clear error: models pass 'path1 path2 path3'.
    Accept list/space-separated paths (split+iterate) instead of erroring.
D3. `\n in regex` error (17): auto-enable multiline when pattern contains \n.

### Cluster E: process/background UX
E1. process(wait) clamps to 60s but models asked for 600 — result says
    "timeout" which reads like failure. Return status=running + explicit
    "not an error" + remaining-runtime estimate, and suggest notify_on_complete.
E2. Duplicate process poll dampening: 511 exact dupes — after 2 identical
    polls with unchanged output, add cooldown note.

### Cluster F: schema diet (33k tokens → target ~20k)
F1. terminal: compress background/notify/watch_patterns prose (1,410→~700 tok)
    — move anecdotes to system-prompt-level or drop; keep hard rules.
F2. execute_code desc 2,454 chars → tighten to ~1,200.
F3. session_search 1,624 tok, cronjob 1,826 tok, computer_use 2,423 tok —
    per-tool rewrite pass with a token budget (500 tok cap for non-core).
F4. Audit duplicated cross-tool guidance (the "Do NOT use cat/grep/sed" block
    is in terminal desc AND system prompt AND file tool descs).

### Cluster G: consolidation / new affordances
G1. write_file returns a short content echo/hash so verify-reads (154) die.
    (Already returns bytes_written; add head/tail preview option? measure)
G2. Heredoc parser blocks (198): the blocker message should point to
    write_file + `bash script.sh` two-step explicitly, with a literal example.
G3. `&`/nohup blocks (200): auto-rewrite? No — keep block but error message
    can include the exact corrected call JSON.

### Cluster H: guardrail tuning
H1. Loop-warning thresholds: same_tool_failure fires at 3; data shows models
    self-correct after 1-2 for cd/gh errors. Fine. But add error-CLASS-aware
    hints (A2) so the first failure carries the recovery info.

## Next steps
1. Baseline battery finishes → per-task turn/error stats.
2. Subagent surveys (other agents' tool designs + research) → merge ideas.
3. Rank by (frequency x cost x implementation risk), implement top N as PRs.
