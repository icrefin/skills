# DSH v4 session format & ZCode mapping

Everything here was read out of the installed Harness bundle
(`/Applications/DeepSeek Harness.app/Contents/Resources/app.asar`) and verified
against a session DSH had already accepted. Where a rule is load-bearing it is
quoted with the function that enforces it.

## Contents

1. [Re-checking the facts after a DSH upgrade](#1-re-checking-the-facts-after-a-dsh-upgrade)
2. [Files and directories](#2-files-and-directories)
3. [Zstandard framing](#3-zstandard-framing)
4. [Session header](#4-session-header)
5. [Event stream and lifecycle](#5-event-stream-and-lifecycle)
6. [Message event shapes](#6-message-event-shapes)
7. [Event vocabulary](#7-event-vocabulary)
8. [Attachments](#8-attachments)
9. [ZCode source schema](#9-zcode-source-schema)
10. [ZCode → DSH mapping](#10-zcode--dsh-mapping)
11. [Pitfall checklist](#11-pitfall-checklist)
12. [Running the Harness's own validator](#12-running-the-harnesss-own-validator)

## 1. Re-checking the facts after a DSH upgrade

`app.asar` is an archive: a JSON header followed by file blobs. Read any file
without extracting the whole bundle:

```python
import struct, json
p = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar'
f = open(p, 'rb')
_, _, _, header_size = struct.unpack('<IIII', f.read(16))
header = json.loads(f.read(header_size)); base = 16 + header_size

def read(path):                      # path like '/dsh/node_modules/.../lib/index.js'
    node = header
    for part in path.strip('/').split('/'):
        node = node['files'][part]
    f.seek(base + int(node['offset']))
    return f.read(node['size'])
```

| File | What it settles |
| --- | --- |
| `@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js` | `scanZstdFrames`, `assertZstdHeaderFrame`, `encodeMaterialization`, `readZstdPrefix` — the physical log rules |
| `@deepseek-ai/dsh-session-persistence-jsonl/README.md` | prose spec of the storage format and crash recovery |
| `@deepseek-ai/dsh-session/lib/index.js` | `validateSessionHeader`, `assertMessageEventShape`, `hasProviderModel` |
| `@deepseek-ai/dsh-session-format/lib/index.js` | `readHeader` — what listing validates |
| `@deepseek-ai/dsh-session-format-v3-to-v4/lib/index.js` | current-row validation, `titleSources`, `sourceEventSeqs` decoding |

## 2. Files and directories

```
$DSH_HOME/
├── sessions/
│   └── --Users-me-proj--/                 ← encoded cwd
│       └── session-<uuid>/
│           ├── session.v4.jsonl.zstd      ← the log
│           └── session.lock               ← empty lock file
├── storages/workspace.json                ← which sessions belong to which workspace
└── attachments/v1/objects/<xx>/<sha256>   ← content-addressed image store
```

- **Encoded directory name**: `"-" + cwd.replace("/", "-") + "--"`.
  `/Users/me/proj` → `--Users-me-proj--` — **two** trailing dashes. This is a
  real trap: one dash off and the logs land in a directory DSH never reads.
  Resolve an existing workspace directory by comparing
  `dir_name.strip("-")` against `cwd.replace("/", "-").strip("-")` instead of
  guessing, and fall back to the derived name only for a brand-new cwd.
- A log lives under the directory for **its own** `cwd`; a session that ran in a
  subdirectory gets the subdirectory's directory name.
- `workspace.json` is `{"unit": {...}, "global": {initialized, defaultWorkspaceId,
  workspaceIds[], archivedSessionIds[], pinnedSessionIds[]}, "tables":
  {"workspaces": {"<uuid>": {path, title, sessionIds[], createdAt, updatedAt}}}}`.
  Append the new ids to the entry whose `path` matches; create the entry and add
  its id to `global.workspaceIds` when absent. Back the file up first.
- Session ids are conventionally `session-<uuid>`. Version-5 UUIDs (the
  deterministic ones this importer derives) are accepted — an earlier successful
  import used them.

## 3. Zstandard framing

> "one checksummed frame containing only the header line, then one checksummed
> frame per durable append batch" — persistence README

```js
// assertZstdHeaderFrame
if (plaintext.length === 0 || plaintext.indexOf(10) !== plaintext.length - 1)
  throw new Error("corrupt Zstandard session log: first frame is not exactly one header line");
```

Consequences for a writer:

- Compress the header line **alone** into frame 0. Frame 1+ hold event lines.
  A single frame containing header *and* events is rejected as corrupt.
- Every frame needs a content checksum. `zstd` CLI: pass `--check` (`-c` for
  stdout). Node: `zlib.zstdCompressSync` checksums by default.
- Frames are independent; plain concatenation is the format. Two frames
  (header + one batch) is exactly what `encodeMaterialization` produces.
- The last byte of the file is a newline; no trailing garbage.
- `scanZstdFrames` walks frame headers/blocks without decompressing and rejects
  invalid magic (`0xFD2FB528`), reserved bits, and reserved block types. An
  incomplete final frame is treated as a torn tail; a complete frame containing
  an unterminated JSONL record is corruption.

## 4. Session header

First line of frame 0. Fields the validator enforces:

| Field | Rule |
| --- | --- |
| `version` | must be `4` |
| `id` | must equal the session id the store uses (matches the directory name) |
| `createdAt` | non-negative safe integer (epoch ms) |
| `cwd` | optional, but if present must be an **absolute** path string |
| `isSeeded` | required boolean |
| `delegationDepth` | optional non-negative safe integer |
| `agentPreset` | optional string |
| `parentSession`, `origin` | optional; `origin` may only be `"subagent"` |
| `seedLength` | **forbidden** — presence is an error |

```json
{"type": "session", "version": 4, "id": "session-…", "createdAt": 1791017076027,
 "cwd": "/Users/me/proj", "isSeeded": false, "delegationDepth": 0, "agentPreset": "standard"}
```

Listing reads and validates only the header frame, so a bad header makes the
session invisible rather than failing loudly.

## 5. Event stream and lifecycle

- Event order: `permission/preset`, `sandbox/mode`, `approval/policy`, then the
  turns.
- `seq` starts at 0 and is contiguous across all events.
- `time` is epoch ms and should never decrease.
- Every surface event carries `surfaceOp` ("append" or a replacement-range
  object); `tool/result` also carries `sourceEventSeqs: [seq of the matching
  tool/call]`.
- Per turn: `turn/start` → `step/start` → (`system/message`, `user/message`) →
  `assistant/message`, `tool/call`, `tool/result` → `step/end` → … →
  `turn/end`.
- One step = one assistant response plus its tool calls. A new step starts when
  the previous `step/end` has been written.
- User/assistant/tool events must sit inside an open turn **and** an open step.
- The log ends with `session/title` then `session/end-seed`.

The `system/message` at the start of each turn is the DSH system prompt. When
importing, take the text from an existing session of the same install rather
than inventing one; it is history, not live configuration.

## 6. Message event shapes

Every **surface** event — `system/message`, `user/message`, `developer/message`,
`assistant/message`, `tool/result` — must declare how it joins the conversation
surface (see `foldSurface` in the v3→v4 codec):

- `"surfaceOp": "append"` for a normal addition, or
- a replacement-range object (`{op: "replace", startSeq, endSeq, …}`) that
  shadows an earlier run of surface nodes and must list the shadowed seqs in
  `sourceEventSeqs`.

The field is **not optional**. `foldSurface` reads
`record(event.surfaceOp, "<type> surfaceOp")` for anything that is not
`"append"`, so a missing field surfaces as
`SessionFormatError: <type> surfaceOp requires an object` — note the confusing
wording: the fix is usually to *add* `"surfaceOp": "append"`.

`assertMessageEventShape` (ported in the converter's verifier) additionally
requires, for `system/message`, `user/message`, `assistant/message`,
`tool/result`:

- an identified message: non-empty string `id`;
- `role` matching the event type (`system`, `user`, `assistant`, `tool`);
- a `source` object with a non-empty string `kind`;
- `content` as an array;
- `system/message` → `source.kind === "system-prompt"`;
- `assistant/message` → `source.kind === "model"` **and** non-empty
  `provider` + `model` strings;
- `tool/result` → `source.kind === "tool"`, non-empty `source.callId`, and
  `message.toolCallId === source.callId`.

For `user/message` the message *is* the event's `data`; for the others it is
`data.message`.

`sourceEventSeqs` is stored compactly: a run of **three or more** consecutive
integers becomes a `[start, end]` pair, anything else stays verbatim, and
decoding expands it back. Single-element lists are therefore written as-is.

`session/title` (see `titleSources`):

- `messageSeqs` must be empty **iff** `source.kind === "user"` — i.e.
  `{"messageSeqs": [], "source": {"kind": "user"}}` for a real title, or
  `{"messageSeqs": [seq], "source": {"kind": "fallback"}}` for a derived one;
- every cited `seq` must point at an *earlier* `user/message` whose
  `source.kind === "user"`, with no repeats.

## 7. Event vocabulary

Events the importer emits, in the shape DSH expects:

```jsonc
{"type":"permission/preset","seq":0,"time":…,"data":{"preset":"workspace-write"}}
{"type":"sandbox/mode","seq":1,"time":…,"data":{"mode":"workspace-write"}}
{"type":"approval/policy","seq":2,"time":…,"data":{"policy":"ask"}}

{"type":"turn/start","seq":3,"time":…,"data":{"turn":1}}
{"type":"step/start","seq":4,"time":…,"data":{"turn":1,"step":1}}

{"type":"system/message","seq":5,"time":…,"surfaceOp":"append","data":{"turn":1,"step":1,"message":{
  "role":"system","content":[{"type":"text","text":"…"}],
  "source":{"kind":"system-prompt"},"id":"<uuid>"}}}

{"type":"user/message","seq":6,"time":…,"surfaceOp":"append","data":{
  "content":[{"type":"text","text":"…"}],
  "source":{"kind":"user"},"role":"user","id":"<uuid>"}}

{"type":"assistant/message","seq":7,"time":…,"surfaceOp":"append","data":{
  "turn":1,"step":1,"stream":[],"message":{
    "role":"assistant",
    "content":[{"type":"reasoning","text":"…"},
               {"type":"text","text":"…"},
               {"type":"tool-call","id":"call_…","name":"Bash","arguments":"{\"command\": \"…\"}"}],
    "source":{"kind":"model","provider":"…","model":"…"},"id":"<uuid>"}}}

{"type":"tool/call","seq":8,"time":…,"data":{
  "turn":1,"step":1,"callId":"call_…","name":"Bash","arguments":"{…}"}}

{"type":"tool/result","seq":9,"time":…,"surfaceOp":"append","sourceEventSeqs":[8],"data":{
  "turn":1,"step":1,"message":{"role":"tool","source":{"kind":"tool","callId":"call_…"},
  "toolCallId":"call_…","content":[{"type":"text","text":"…"}],"isError":false,"id":"<uuid>"}}}

{"type":"step/end","seq":10,"time":…,"data":{"turn":1,"step":1}}
{"type":"turn/end","seq":11,"time":…,"data":{"turn":1,"reason":{"kind":"completed"}}}

{"type":"session/title","seq":12,"time":…,"data":{"title":"…","messageSeqs":[],"source":{"kind":"user"}}}
{"type":"session/end-seed","seq":13,"time":…,"data":{}}
```

`reasoning` blocks carry the model's thinking; `arguments` is a JSON **string**,
not an object. Preserve the source tool's original name (`Bash`, `Read`,
`TodoWrite`, `mcp__ida__execute_python`) — history renders by name and the names
are what the model actually saw.

An `image` content block references the attachment store:

```json
{"type": "image", "attachment": {"attachmentId": "sha256:<hex>", "mediaType": "image/png",
 "bytes": 197559, "width": 780, "height": 1688, "name": "shot.png"}}
```

## 8. Attachments

`$DSH_HOME/attachments/v1/objects/<first two hex chars>/<full sha256 hex>`, no
extension, raw bytes. Compute the digest from the bytes you write; the
`attachmentId` is `sha256:<digest>`. Copying bytes in is enough — there is no
index file.

Two traps, both of which produce a *turn-level* failure in the GUI rather than a
load error:

- **The bytes must be the image itself.** ZCode artifact files are normally
  `data:image/png;base64,iVBORw0…` **text files** whose extension is even `.txt`,
  and their size on disk is the base64 length — not the image size. Store the
  base64-decoded payload and hash *that*; a store holding the data URI verbatim
  yields `Unsupported or malformed image data` when the turn renders. ZCode's
  `metadata.image.transformedSizeBytes` is the decoded length and is a good
  cross-check; `metadata.sizeBytes` is the encoded length.
- **Verify the magic bytes.** Only emit an `image` block when the payload starts
  with a known signature (`\x89PNG\r\n\x1a\n`, `\xff\xd8\xff`, `GIF87a/89a`,
  `RIFF….WEBP`); otherwise drop the block and leave the `[Attached image/…]`
  text the model actually saw.

`width`/`height` are optional — real DSH logs contain image blocks without them —
but they are easy to derive from the header (PNG at bytes 16-24, JPEG by walking
segments to the SOF marker, GIF at bytes 6-10, WebP in the `VP8X`/`VP8 ` chunk)
and give the client a layout hint before it decodes.

After importing, re-read every image block from disk, re-hash each referenced
object, and confirm the file decodes (Pillow is bundled with the DSH runtime
Python). Digest equality alone only proves you copied the bytes you hashed.

## 9. ZCode source schema

Read-only, `~/.zcode/cli/db/db.sqlite`:

- `session(id, project_id, workspace_id, parent_id, slug, directory, title,
  time_created, time_updated, task_type, …)` — `directory` is the cwd; match the
  target workspace on it (add `like '<workspace>/%'` to include subdirectories).
- `message(id, session_id, time_created, time_updated, data)` — `data.role`,
  `data.time.{created,completed}`, `data.providerId`, `data.modelId`,
  `data.finish`, and `data.semantics.{kind,origin,transcriptVisibility}`.
  `semantics.kind` is one of `user_prompt`, `todo_reminder`,
  `background_notification`, `assistant_response`, `timeline_event`.
- `part(id, message_id, session_id, time_created, time_updated, data, sequence)`
  — `data.type` ∈ `text`, `reasoning`, `tool`, `step-start`, `step-finish`,
  `timeline`, `file`. A tool part is
  `{callID, tool, declarationIndex, state:{status, input, output|error, title,
  time:{start,end}, attachments[], metadata}}`; `output` is a string (truncated
  by ZCode around 50 000 chars), `status` is `completed` or `error`, and `error`
  cases carry no `output`.

Images: `data.url` is `zcode-artifact://<session_id>/<name>`; the bytes live in
`~/.zcode/cli/artifacts/<session_id>/` under a file whose name *contains* that
`<name>` (often prefixed with the upload name). Match by substring, sizing
against `metadata.sizeBytes`.

Open the database with `file:<path>?mode=ro`; fall back to `?immutable=1` when
the sandbox cannot create a journal next to it. `immutable=1` ignores the WAL,
so prefer `mode=ro` when it works.

## 10. ZCode → DSH mapping

| ZCode | DSH |
| --- | --- |
| `session.time_created` | header `createdAt` |
| `session.directory` | header `cwd` + destination directory |
| `session.title` | `session/title` with `source.kind: "user"`; when empty, a 60-char fallback from the first prompt with `source.kind: "fallback"` and `messageSeqs: [first user seq]` |
| `user_prompt` message | `turn/start`, `step/start`, `system/message`, `user/message` |
| `todo_reminder` / `background_notification` | buffered, emitted immediately **after the next `step/start`** — ZCode injects them ahead of a model call, so they belong to the step they were delivered into |
| `assistant_response` message | `step/start` (only if none open), `assistant/message`, then `tool/call` + `tool/result` per tool part, then `step/end` |
| `timeline_event`, assistant messages with no content parts | skipped (ZCode aborted turns leave a bare `step-start`) |
| next `user_prompt` | closes the previous `turn/end` at that prompt's timestamp; a final `turn/end` closes the last turn |
| text / reasoning / tool parts | `text` / `reasoning` / `tool-call` blocks on the assistant message, in part order |
| `state.time.start` / `state.time.end` | `tool/call` / `tool/result` timestamps |
| `state.output` / `state.error` | result content, `isError` from `status == "error"` |
| `file` parts and `state.attachments` | artifact file read, base64-decoded, magic-checked, then copied into the DSH attachment store and emitted as `image` blocks |
| — | `session/end-seed` appended last |

Message ids are derived with UUIDv5 over the ZCode message id, and session ids
with UUIDv5 over the ZCode session id, which makes re-running the importer
idempotent (an existing target file is skipped unless `--force`).

Provider ids are ZCode-internal UUIDs (occasionally a literal like
`new-provider`) and are not resolvable from local config; they are carried
through verbatim as provenance. Only the `provider`/`model` strings matter to
DSH, and they must be non-empty.

## 11. Pitfall checklist

- Wrong directory name (one dash instead of two) → files written, nothing listed.
- Header sharing a frame with events → "first frame is not exactly one header line".
- Missing frame checksum → checksum validation failure.
- A surface event without `surfaceOp` → `<type> surfaceOp requires an object`
  (this one slipped through a full port of `assertMessageEventShape`, because
  that function never looks at `surfaceOp`).
- `system/message` without `source.kind: "system-prompt"` → invalid source.
- Assistant source without `provider`/`model` → invalid model source.
- `tool/result` whose `toolCallId` differs from `source.callId` → rejected.
- `sourceEventSeqs` not pointing at the matching `tool/call` seq → rejected.
- `session/title` with `messageSeqs` non-empty but `source.kind: "user"` → rejected.
- Timestamps that go backwards (e.g. an injected message stamped before the step
  it was attached to) → clamp to the previous event's time.
- A `data:` URI copied into the attachment store as if it were the image →
  `Unsupported or malformed image data` when that turn renders (no load error,
  so it only shows up when the user scrolls there).
- Rewriting a session log that the Harness has continued (a live `--force`
  re-import) → the Harness appends from its own seq counter, leaving a gap:
  `released v2 row N has seq gap (expected N, got M)`. Repair by shifting the
  appended tail down to close the gap and renumbering its turns consecutively
  (`turn/start` must open exactly `nextTurn`, steps exactly `nextStep`), then
  re-run the validator; keep the corrupt file as a backup first.
- Assuming the GUI updates itself: a running DSH server caches its session list.

## 12. Running the Harness's own validator

Re-implementing the rules is how a corrupt import passes review. The bundle
ships the real validator, and it is small enough to lift out and run:

```bash
node scripts/validate_session_log.mjs path/to/session.v4.jsonl.zstd
```

The script:

1. parses the asar header and extracts the dependency closure of
   `@deepseek-ai/dsh-session-format-v3-to-v4` (plus `dsh-session` for
   `KNOWN_SESSION_EVENT_TYPES`) into a temp cache keyed by the bundle's size and
   mtime;
2. decompresses the log, splitting concatenated Zstandard frames itself, and
   enforces the header-frame rule;
3. calls `restoreReleasedV4Artifact({header, inheritedEventCount, events},
   KNOWN_SESSION_EVENT_TYPES)` — the same entry point the Harness uses (the
   inherited count derived from the log's inherited end-seed marker) — and
   reports the resulting `SessionFormatError` verbatim.

Two details that cost time when wiring this up by hand:

- **The stored header carries `"type": "session"`; the decoded header must not.**
  `assertReleasedV4Header` rejects any field outside
  `{version, id, createdAt, isSeeded, delegationDepth, cwd, parentSession,
  origin, agentPreset}`, so strip `type` before calling.
- **The asar data section starts after 2 bytes of alignment padding** past
  `16 + headerSize` in the 0.2.x bundle. Deriving the exact base by probing where
  a known file (a `package.json`) must start is more robust than hard-coding the
  padding.
- **Seeded logs need the right `inheritedEventCount`.** `restoreReleasedV4Artifact`
  compares it against the index of the last `session/end-seed` whose data carries
  `{inherited: true}` and rejects the log otherwise; for a forked/subagent session
  pass that marker's own `seq`, not zero and not `seq + 1`.

The validator accepts what DSH accepts: use a session written by DSH itself, and
one known-broken file, as calibration before trusting a run.