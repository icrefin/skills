---
name: zcode-session-import
description: Import ZCode (Z.ai) chat sessions into DeepSeek Harness as native, resumable DSH sessions, and write or repair DSH v4 session logs by hand. Use when asked to import/bring over/migrate ZCode session history into DSH, to continue an old ZCode conversation inside DeepSeek Harness, to move chat history between the two tools, or when a DSH session artifact (session.v4.jsonl.zstd) must be synthesized, inspected, or fixed so the Harness can load it.
---

# Importing ZCode sessions into DSH

`scripts/zcode_to_dsh_import.py` converts ZCode's SQLite store into DSH v4 session
logs. It reads ZCode read-only, is idempotent, and self-verifies every file it
writes against the invariants DSH enforces on load.

## Run it

Dry run first — it stages the logs in a local directory and touches nothing else:

```bash
python3 scripts/zcode_to_dsh_import.py --workspace "$PWD" --out ./.zcode-import-stage
```

Then apply. `--apply` writes into `$DSH_HOME` (`~/.dsh`), which is normally
outside the session workspace: if the file sandbox blocks it, re-run the apply
step with escalated permissions rather than moving files by hand.

```bash
python3 scripts/zcode_to_dsh_import.py --workspace "$PWD" --apply
```

Useful flags: `--list` (what would match), `--include-subdirs` (also sessions
ZCode ran from a subdirectory of the workspace), `--session <sess_id>` (one
session), `--force` (rewrite, always keeps a timestamped backup),
`--overwrite-continued` (see the warning below), `--no-attachments`,
`--dsh-home`, `--db`.

Requires the `zstd` CLI, falling back to Node 24's `zlib`.

## Never rewrite a session the Harness has continued

Re-running an import is idempotent — an existing log is skipped. **`--force` is
the dangerous one**: if the user has since opened that session and sent a
message, DSH has appended live events to the log, and rewriting the file
underneath it destroys them. Worse, the running Harness keeps its own
next-sequence counter, so the *next* message it appends starts where its counter
is, not where the file ends, and the session is left permanently unreadable:

```
stored log is corrupt: Error: corrupt session log: invalid committed event at
line 943: released v2 row 942 has seq gap (expected 942, got 960)
```

The importer now compares the existing log with what it would write: a log with
our exact prefix plus extra events is **refused** (`REFUSED (continued in DSH,
+N live event(s))`) and `--force` alone will not overwrite it. Overriding that
(`--overwrite-continued`) is only correct with DSH closed, and it still silently
drops the user's messages — prefer leaving the session alone, or importing it
into a fresh session.

Corollary: never delete or rewrite attachment objects while a session that
references them is live; the Harness's in-memory projection still points at the
old ids and the next turn dies with `Attachment object is missing.`

## What to tell the user afterwards

The log files and the `workspace.json` registration are in place immediately,
but a **running DSH server keeps its session list in memory** and will not show
new sessions until the GUI reloads; if they are still missing, restart the DSH
app. Say this explicitly instead of claiming the import is visible.

## Rules that decide success

DSH rejects a session log wholesale if any of these is wrong — the session
silently disappears from the list, so treat them as hard requirements:

1. **The first Zstandard frame must contain exactly the header line.** DSH
   asserts `first frame is not exactly one header line`. Never compress header
   plus events into one frame; write the header as its own frame, then one frame
   per append batch. Every frame must carry a content checksum.
2. **Every surface event carries `surfaceOp: "append"`.** That is
   `system/message`, `user/message`, `developer/message`, `assistant/message`,
   and `tool/result`. Omitting it fails the read with
   `<type> surfaceOp requires an object`: the event is otherwise fine, so an
   importer that forgets it *looks* correct until the history is opened.
3. **Every message event needs `role`, a non-empty `id`, a `source` with a
   non-empty `kind`, and an array `content`.** A `system/message` must have
   `source.kind === "system-prompt"`; an `assistant/message` must have
   `source.kind === "model"` with non-empty `provider` and `model`.
4. **Session directory name = the cwd with `/` folded to `-`, wrapped in `--`
   on both sides**: `/Users/me/proj` → `--Users-me-proj--` (note *two* trailing
   dashes). Each log lives under the directory for *its own* `cwd`.
5. `seq` starts at 0 and is contiguous; `time` is epoch ms and never decreases.
6. Turns and steps stay balanced: `turn/start` → `step/start` → messages →
   `step/end` → `turn/end`, with user/assistant/tool events never outside an
   open turn and step.
7. **Store decoded image bytes and check them before writing.** A ZCode artifact
   file is usually `data:<mime>;base64,<payload>` *text*; copying that file
   verbatim into the attachment store makes the GUI fail the turn with
   `Unsupported or malformed image data`. Base64-decode it, hash the decoded
   bytes, and refuse to write a blob whose magic bytes are not a real image
   (PNG/JPEG/GIF/WEBP) — keep the `[Attached image/...]` text marker instead.

Full format details, validation sources, and the ZCode→DSH field mapping are in
[references/dsh-session-format-v4.md](references/dsh-session-format-v4.md) — read
it before hand-editing a log or changing the converter.

## Verify with DSH's own reader

Hand-rolled checks are not enough: two imports passed every rule an agent had
ported and were still rejected by the Harness. Always finish by running the
Harness's own validator, which lifts the real codec out of the installed
`app.asar` and calls `restoreReleasedV4Artifact` on the file:

```bash
node scripts/validate_session_log.mjs ~/.dsh/sessions/<dir>/<session>/session.v4.jsonl.zstd
node scripts/validate_session_log.mjs <staged-file>          # also works on --out staging
```

It prints `OK` or the exact `SessionFormatError` the Harness would raise, and
pairs well with `node scripts/validate_session_log.mjs $(ls …)` over a whole
workspace. Run it on the staged output *before* applying, and on every file after
applying.

Keep these supporting checks too:

- **Positive reference**: diff your output against a session DSH already accepts
  — event types, event-level *and* payload keys, and ordering. Compare full key
  sets, not just message keys; a top-level field like `surfaceOp` lives outside
  `data` and is easy to miss.
- **Negative controls**: point the validator at a log you have deliberately
  broken and confirm it reports exactly that fault. A verifier that never fails
  proves nothing.
- **On-disk readback**: re-decompress the written file rather than trusting the
  bytes in memory; `--out <dir>` is the supported way to inspect output without
  touching `~/.dsh`.

The converter additionally runs its own fast `verify_session_bytes` on every file
it writes, so obvious faults never reach `~/.dsh` — but that port only
approximates the rules above.

## Source facts to re-check when DSH changes

The format rules above were read out of the installed Harness bundle. If DSH is
upgraded, re-read them from `app.asar` (the reference lists the exact paths and
function names) before trusting this skill.