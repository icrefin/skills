#!/usr/bin/env python3
"""Import ZCode sessions of one workspace into DeepSeek Harness (DSH).

What it does
------------
* Reads ZCode's SQLite store (``~/.zcode/cli/db/db.sqlite``) strictly
  read-only.
* Rebuilds every session whose ``directory`` equals the target workspace as a
  native DSH session log (``session.v4.jsonl.zstd``, format version 4).
* Optionally registers the imported sessions in DSH's workspace storage
  (``$DSH_HOME/storages/workspace.json``) and copies referenced images into
  DSH's content-addressed attachment store.

Nothing in ZCode is modified. Import is deterministic: session ids are
derived from the ZCode session id via UUIDv5, so re-running skips what is
already there.

Usage
-----
    # preview (writes nothing outside --out)
    python3 scripts/dsh/zcode_to_dsh_import.py --workspace "$PWD" --out ./_zcode_import

    # for real (needs write access to $DSH_HOME)
    python3 scripts/dsh/zcode_to_dsh_import.py --workspace "$PWD" --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Deterministic-id namespace for imported sessions (fixed forever).
IMPORT_NAMESPACE = uuid.UUID("6f0d5b3c-2f4a-4a1e-9c2b-1d8f5a7e3b90")

TEXT_PART_LIMIT = 4_000_000  # safety valve, ZCode already truncates at 50k


# --------------------------------------------------------------------------
# ZCode side
# --------------------------------------------------------------------------
def open_zcode_db(db_path: Path) -> sqlite3.Connection:
    """Open ZCode's SQLite DB read-only without ever writing to it."""
    for uri in (
        f"file:{db_path}?mode=ro",
        f"file:{db_path}?immutable=1",
    ):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=10)
            conn.execute("select count(*) from session").fetchone()
            return conn
        except sqlite3.Error:
            continue
    raise SystemExit(
        f"cannot read ZCode database at {db_path} (needs read access; the "
        f"parent directory must be readable)"
    )


def load_sessions(conn: sqlite3.Connection, workspace: str, descendants: bool = False):
    cols = ("id", "title", "time_created", "time_updated", "parent_id", "task_type",
            "directory")
    if descendants:
        root = workspace.rstrip(os.sep)
        rows = conn.execute(
            f"select {', '.join(cols)} from session "
            f"where directory = ? or directory like ? order by time_created",
            (workspace, root + os.sep + "%"),
        ).fetchall()
    else:
        rows = conn.execute(
            f"select {', '.join(cols)} from session where directory = ? "
            f"order by time_created",
            (workspace,),
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def load_messages(conn: sqlite3.Connection, session_id: str):
    rows = conn.execute(
        "select id, data from message where session_id = ? "
        "order by time_created, rowid",
        (session_id,),
    ).fetchall()
    return [(mid, json.loads(data)) for mid, data in rows]


def load_parts(conn: sqlite3.Connection, session_id: str):
    rows = conn.execute(
        "select message_id, data from part where session_id = ? "
        "order by message_id, sequence, rowid",
        (session_id,),
    ).fetchall()
    parts: dict[str, list[dict]] = {}
    for mid, data in rows:
        parts.setdefault(mid, []).append(json.loads(data))
    return parts


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def det_uuid(*parts: str) -> str:
    return str(uuid.uuid5(IMPORT_NAMESPACE, "\u0000".join(parts)))


def now_ms() -> int:
    return int(time.time() * 1000)


def msg_ts(message: dict, key: str = "created", default: int | None = None) -> int:
    t = message.get("time") or {}
    val = t.get(key)
    if val is None:
        val = t.get("created")
    if val is None:
        val = default if default is not None else now_ms()
    return int(val)


def workspace_dir_name(cwd: str) -> str:
    """DSH names the per-workspace session directory after the cwd path.

    ``/Users/me/proj`` -> ``--Users-me-proj--`` (only ``/`` is folded to ``-``).
    """
    return "-" + cwd.replace(os.sep, "-") + "--"


def encode_text(text: str) -> str:
    if len(text) > TEXT_PART_LIMIT:
        return text[:TEXT_PART_LIMIT] + "\n\n[...truncated by zcode import...]"
    return text


def find_existing_workspace_dir(dsh_home: Path, workspace: str) -> Path | None:
    """Find the session directory DSH already uses for this workspace."""
    root = dsh_home / "sessions"
    key = workspace.replace(os.sep, "-").strip("-")
    if not root.is_dir():
        return None
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.strip("-") == key:
            return entry
    return None


class AttachmentStore:
    """Copies ZCode image artifacts into DSH's content-addressed store.

    ZCode artifact files are usually ``data:<mime>;base64,<payload>`` text, not
    raw image bytes: the *decoded* payload is what DSH's image decoder needs, so
    the digest, the stored blob and the reported byte count all come from the
    decoded form.
    """

    def __init__(self, dsh_home: Path, artifacts_root: Path, enabled: bool):
        self.objects = dsh_home / "attachments" / "v1" / "objects"
        self.artifacts_root = artifacts_root
        self.enabled = enabled
        self.copied = 0
        self.missing = 0
        self.undecodable = 0
        self._cache: dict[str, dict | None] = {}

    def resolve(self, session_id: str, uri: str) -> Path | None:
        """zcode-artifact://<session>/<name> -> file on disk."""
        name = uri.split("/", 3)[-1] if "://" in uri else uri
        root = self.artifacts_root / session_id
        if not root.is_dir():
            return None
        for cand in sorted(root.iterdir()):
            if name and name in cand.name:
                return cand
        return None

    @staticmethod
    def decode_payload(raw: bytes) -> tuple[bytes, str | None]:
        """Return (image bytes, media type) from raw or data-URI content."""
        if not raw.startswith(b"data:"):
            return raw, None
        try:
            header, payload = raw.split(b",", 1)
        except ValueError:
            return b"", None
        head = header.decode("ascii", errors="replace")
        media_type = head[5:].split(";")[0] or None
        if ";base64" not in head:
            return b"", media_type  # non-base64 data URIs are not supported
        try:
            import base64
            return base64.b64decode(payload, validate=False), media_type
        except Exception:
            return b"", media_type

    def register(self, session_id: str, uri: str) -> dict | None:
        """Return a DSH attachment descriptor for a ZCode artifact URI."""
        if uri in self._cache:
            return self._cache[uri]
        path = self.resolve(session_id, uri)
        if path is None or not path.is_file():
            self.missing += 1
            self._cache[uri] = None
            return None
        try:
            blob, media_type = self.decode_payload(path.read_bytes())
        except OSError:
            self.missing += 1
            self._cache[uri] = None
            return None
        if not blob or image_format(blob) is None:
            # Never store bytes an image decoder would reject ("Unsupported or
            # malformed image data"); the transcript keeps its text marker.
            self.undecodable += 1
            self._cache[uri] = None
            return None
        digest = hashlib.sha256(blob).hexdigest()
        attachment_id = f"sha256:{digest}"
        if self.enabled:
            dest = self.objects / digest[:2] / digest
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(digest + ".tmp")
                tmp.write_bytes(blob)
                os.replace(tmp, dest)
            self.copied += 1
        descriptor = {"attachmentId": attachment_id, "bytes": len(blob)}
        if media_type:
            descriptor["mediaType"] = media_type
        dims = image_dimensions(blob)
        if dims:
            descriptor["width"], descriptor["height"] = dims
        self._cache[uri] = descriptor
        return descriptor


IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_format(blob: bytes) -> str | None:
    """Return the media type of a recognized image payload, else None."""
    for magic, media_type in IMAGE_MAGIC:
        if blob.startswith(magic):
            return media_type
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_dimensions(blob: bytes) -> tuple[int, int] | None:
    """Read pixel dimensions from an image header, without a decoder library."""
    try:
        if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24:
            return int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big")
        if blob.startswith(b"GIF") and len(blob) >= 10:
            return int.from_bytes(blob[6:8], "little"), int.from_bytes(blob[8:10], "little")
        if blob.startswith(b"\xff\xd8"):  # JPEG: walk segments to the frame header
            i = 2
            while i + 9 < len(blob):
                if blob[i] != 0xFF:
                    i += 1
                    continue
                marker = blob[i + 1]
                if marker == 0xDA:  # start of scan: no metadata past here
                    return None
                if marker == 0x01 or 0xD0 <= marker <= 0xD8:
                    i += 2
                    continue
                length = int.from_bytes(blob[i + 2:i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height = int.from_bytes(blob[i + 5:i + 7], "big")
                    width = int.from_bytes(blob[i + 7:i + 9], "big")
                    return width, height
                i += 2 + length
        if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP" and len(blob) >= 30:
            chunk = blob[12:16]
            if chunk == b"VP8X":
                width = 1 + int.from_bytes(blob[24:27], "little")
                height = 1 + int.from_bytes(blob[27:30], "little")
                return width, height
            if chunk == b"VP8 " and blob[23:26] == b"\x9d\x01\x2a":
                width = int.from_bytes(blob[26:28], "little") & 0x3FFF
                height = int.from_bytes(blob[28:30], "little") & 0x3FFF
                return width, height
    except (IndexError, ValueError):
        return None
    return None


def check_attachments(events: list[dict], objects: Path) -> list[str]:
    """Every referenced image must exist in the store and decode as an image."""
    problems: list[str] = []
    for event in events:
        data = event.get("data") or {}
        for block in (data.get("message") or {}).get("content") or data.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "image":
                continue
            digest = str((block.get("attachment") or {}).get("attachmentId", "")).split(":")[-1]
            blob_path = objects / digest[:2] / digest
            if not blob_path.is_file():
                problems.append(f"seq {event.get('seq')}: image {digest[:12]} missing from store")
                continue
            blob = blob_path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != digest:
                problems.append(f"seq {event.get('seq')}: image {digest[:12]} digest mismatch")
            if image_format(blob) is None:
                problems.append(f"seq {event.get('seq')}: image {digest[:12]} is not decodable image data")
    return problems


# --------------------------------------------------------------------------
# event building
# --------------------------------------------------------------------------
class SessionBuilder:
    def __init__(
        self,
        session: dict,
        workspace: str,
        dsh_session_id: str,
        system_content: list | None,
        attachments: AttachmentStore,
    ):
        self.session = session
        self.zid = session["id"]
        self.workspace = workspace
        self.dsh_session_id = dsh_session_id
        self.system_content = system_content
        self.attachments = attachments
        self.events: list[dict] = []
        self.seq = -1
        self.last_time = int(session["time_created"])
        self.turn = 0
        self.step = 0
        self.step_open = False
        self.pending_injected: list[tuple[int, dict]] = []
        self.stats = {"user": 0, "assistant": 0, "tool": 0, "tool_error": 0,
                      "reasoning": 0, "images": 0, "skipped": 0}
        self.first_user_seq: int | None = None
        self.first_user_text = ""

    # -- low level ---------------------------------------------------------
    def emit(self, etype: str, data: dict, when: int, **extra) -> int:
        when = int(when)
        if when < self.last_time:  # keep the log monotonic
            when = self.last_time
        self.last_time = when
        self.seq += 1
        event = {"type": etype, "seq": self.seq, "time": when, "data": data}
        event.update(extra)
        self.events.append(event)
        return self.seq

    def open_step(self, when: int):
        if self.step_open:
            return
        self.step += 1
        self.step_open = True
        self.emit("step/start", {"turn": self.turn, "step": self.step}, when)
        self.flush_injected()

    def flush_injected(self):
        """ZCode injects runtime notes (todo reminders, task notifications)
        ahead of a model call, so they belong inside the step they were
        delivered to."""
        pending, self.pending_injected = self.pending_injected, []
        for when, data in pending:
            self.emit("user/message", data, when, surfaceOp="append")
            self.stats["user"] += 1

    def close_step(self, when: int):
        if not self.step_open:
            return
        self.emit("step/end", {"turn": self.turn, "step": self.step}, when)
        self.step_open = False

    # -- content -----------------------------------------------------------
    def image_block(self, part: dict) -> dict | None:
        uri = part.get("url") or (part.get("metadata") or {}).get("artifactUri") or ""
        if not uri.startswith("zcode-artifact://"):
            return None
        desc = self.attachments.register(self.zid, uri)
        if not desc:
            return None
        meta = ((part.get("metadata") or {}).get("image") or {})
        block = {
            "type": "image",
            "attachment": {
                "attachmentId": desc["attachmentId"],
                # the decoded payload's own type wins over ZCode's metadata
                "mediaType": desc.get("mediaType") or part.get("mime") or "image/png",
                "bytes": desc.get("bytes") or 0,
                "name": part.get("filename") or "image",
            },
        }
        if meta.get("width"):
            block["attachment"]["width"] = meta["width"]
        if meta.get("height"):
            block["attachment"]["height"] = meta["height"]
        if not (block["attachment"].get("width") and block["attachment"].get("height")):
            if desc.get("width") and desc.get("height"):
                block["attachment"]["width"] = desc["width"]
                block["attachment"]["height"] = desc["height"]
        self.stats["images"] += 1
        return block

    def content_from_parts(self, parts: list[dict]) -> list[dict]:
        content: list[dict] = []
        for part in parts:
            ptype = part.get("type")
            if ptype == "reasoning":
                text = encode_text(part.get("text") or "")
                if text.strip():
                    content.append({"type": "reasoning", "text": text})
                    self.stats["reasoning"] += 1
            elif ptype == "text":
                text = encode_text(part.get("text") or "")
                if text.strip():
                    content.append({"type": "text", "text": text})
            elif ptype == "tool":
                content.append(
                    {
                        "type": "tool-call",
                        "id": part.get("callID") or det_uuid("call", self.zid, str(len(content))),
                        "name": part.get("tool") or "tool",
                        "arguments": json.dumps(
                            (part.get("state") or {}).get("input") or {},
                            ensure_ascii=False,
                        ),
                    }
                )
            elif ptype == "file":
                block = self.image_block(part)
                if block:
                    content.append(block)
        return content

    # -- message handlers --------------------------------------------------
    def add_user_prompt(self, message: dict, parts: list[dict]):
        created = msg_ts(message, "created")
        if self.turn >= 1:  # close the previous turn at this prompt's timestamp
            self.close_step(created)
            self.emit("turn/end",
                      {"turn": self.turn, "reason": {"kind": "completed"}}, created)
        self.turn += 1
        self.step = 0
        self.step_open = False
        self.emit("turn/start", {"turn": self.turn}, created)
        self.open_step(created)
        if self.system_content is not None:
            self.emit(
                "system/message",
                {
                    "turn": self.turn,
                    "step": self.step,
                    "message": {
                        "role": "system",
                        "content": self.system_content,
                        "source": {"kind": "system-prompt", "importedFrom": "zcode"},
                        "id": det_uuid("system", self.zid, str(self.turn)),
                    },
                },
                created,
                surfaceOp="append",
            )
        content = self.content_from_parts(parts)
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        if not content:
            content = [{"type": "text", "text": ""}]
        if self.first_user_seq is None:
            self.first_user_seq = self.seq + 1
            self.first_user_text = text
        self.emit(
            "user/message",
            {
                "content": content,
                "source": {"kind": "user", "importedFrom": "zcode"},
                "role": "user",
                "id": det_uuid("msg", message.get("id") or ""),
            },
            created,
            surfaceOp="append",
        )
        self.stats["user"] += 1

    def add_user_injected(self, message: dict, parts: list[dict]):
        created = msg_ts(message, "created")
        sem = message.get("semantics") or {}
        content = self.content_from_parts(parts)
        if not content:
            return
        self.pending_injected.append(
            (
                created,
                {
                    "content": content,
                    "source": {
                        "kind": "zcode-agent-runtime",
                        "form": sem.get("kind") or "injected",
                        "importedFrom": "zcode",
                    },
                    "role": "user",
                    "id": det_uuid("msg", message.get("id") or ""),
                },
            )
        )

    def add_assistant(self, message: dict, parts: list[dict]):
        created = msg_ts(message, "created")
        completed = msg_ts(message, "completed", created)
        content = self.content_from_parts(parts)
        if not content:
            self.stats["skipped"] += 1
            return
        if self.turn == 0:  # session starts with an assistant turn
            self.turn = 1
            self.step = 0
            self.emit("turn/start", {"turn": self.turn}, created)
        self.open_step(created)

        source = {"kind": "model", "importedFrom": "zcode"}
        provider = message.get("providerId")
        model = message.get("modelId")
        # DSH requires a model source to carry a non-empty provider/model pair.
        source["provider"] = provider if isinstance(provider, str) and provider else "zcode"
        source["model"] = model if isinstance(model, str) and model else "unknown"

        self.emit(
            "assistant/message",
            {
                "turn": self.turn,
                "step": self.step,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "source": source,
                    "id": det_uuid("msg", message.get("id") or ""),
                },
                "stream": [],
            },
            created,
            surfaceOp="append",
        )
        self.stats["assistant"] += 1

        # tool invocations, in declaration order
        for part in parts:
            if part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            call_id = part.get("callID") or det_uuid("call", self.zid, str(part.get("id")))
            name = part.get("tool") or "tool"
            arguments = json.dumps(state.get("input") or {}, ensure_ascii=False)
            call_seq = self.emit(
                "tool/call",
                {
                    "turn": self.turn,
                    "step": self.step,
                    "callId": call_id,
                    "name": name,
                    "arguments": arguments,
                },
                int((state.get("time") or {}).get("start") or created),
            )
            is_error = state.get("status") == "error"
            result_content: list[dict] = []
            if is_error:
                result_content.append(
                    {"type": "text", "text": encode_text(state.get("error") or "")}
                )
                self.stats["tool_error"] += 1
            else:
                output = state.get("output")
                if isinstance(output, str) and output:
                    result_content.append({"type": "text", "text": encode_text(output)})
                elif output is not None:
                    result_content.append(
                        {"type": "text", "text": json.dumps(output, ensure_ascii=False)}
                    )
            for att in state.get("attachments") or []:
                block = self.image_block(att)
                if block:
                    result_content.append(block)
            if not result_content:
                result_content.append({"type": "text", "text": ""})
            self.emit(
                "tool/result",
                {
                    "turn": self.turn,
                    "step": self.step,
                    "message": {
                        "role": "tool",
                        "source": {"kind": "tool", "callId": call_id},
                        "toolCallId": call_id,
                        "content": result_content,
                        "isError": is_error,
                        "id": det_uuid("res", message.get("id") or "", call_id),
                    },
                },
                int((state.get("time") or {}).get("end") or completed),
                surfaceOp="append",
                sourceEventSeqs=[call_seq],
            )
            self.stats["tool"] += 1

        self.close_step(completed)

    # -- driver ------------------------------------------------------------
    def build(self, messages, parts_by_msg) -> tuple[dict, list[dict]]:
        created = int(self.session["time_created"])
        self.emit("permission/preset", {"preset": "workspace-write"}, created + 1)
        self.emit("sandbox/mode", {"mode": "workspace-write"}, created + 2)
        self.emit("approval/policy", {"policy": "ask"}, created + 3)
        last_time = created
        for mid, message in messages:
            parts = parts_by_msg.get(mid, [])
            role = message.get("role")
            kind = (message.get("semantics") or {}).get("kind")
            if role == "user" and kind == "user_prompt":
                self.add_user_prompt(message, parts)
            elif role == "user":
                self.add_user_injected(message, parts)
            elif role == "assistant" and kind == "assistant_response":
                self.add_assistant(message, parts)
            else:  # timeline separators and other bookkeeping
                self.stats["skipped"] += 1
            last_time = max(last_time, msg_ts(message, "completed", msg_ts(message)))

        if self.turn == 0:
            # nothing importable (e.g. only timeline events)
            return {}, []
        if self.pending_injected:
            self.open_step(last_time)  # nothing more will follow: surface them
            self.flush_injected()
        self.close_step(last_time)
        self.emit("turn/end", {"turn": self.turn, "reason": {"kind": "completed"}}, last_time)

        title = (self.session.get("title") or "").strip()
        if title:
            title_data = {"title": title, "messageSeqs": [], "source": {"kind": "user"}}
        else:
            fallback = re.sub(r"\s+", " ", self.first_user_text).strip()[:60]
            title_data = {
                "title": fallback,
                "messageSeqs": [self.first_user_seq] if self.first_user_seq else [],
                "source": {"kind": "fallback"},
            }
        self.emit("session/title", title_data, last_time)
        self.emit("session/end-seed", {}, now_ms())

        header = {
            "type": "session",
            "version": 4,
            "id": self.dsh_session_id,
            "createdAt": int(self.session["time_created"]),
            "cwd": self.workspace,
            "isSeeded": False,
            "delegationDepth": 0,
            "agentPreset": "standard",
        }
        return header, self.events


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def read_event_rows(path: Path) -> list[dict]:
    """Parse an existing session log (header + events) from disk."""
    blob = path.read_bytes()
    frames, _ = scan_frames(blob)
    rows: list[dict] = []
    for start, length, _checksum in frames:
        rows.extend(json.loads(line) for line
                    in _decompress(blob[start:start + length]).decode().splitlines()
                    if line.strip())
    return rows


def inspect_existing(path: Path, events: list[dict]) -> tuple[str, int]:
    """Classify an existing log against the events we are about to write.

    Returns ``(state, extra)``: ``'same'`` for a plain re-import, ``'continued'``
    when the Harness appended live events after our import, ``'diverged'``
    otherwise. ``extra`` is how many events the file has beyond ours.

    Overwriting a *continued* log destroys the session: the running Harness
    keeps its own next-sequence counter, so replacing the file underneath it
    leaves a permanent seq gap and the log becomes unreadable
    (``released v2 row N has seq gap``).
    """
    try:
        rows = read_event_rows(path)
    except Exception:
        return "diverged", 0
    existing = rows[1:]
    extra = len(existing) - len(events)
    if extra < 0:
        return "diverged", extra
    if not all(existing[i].get("seq") == events[i].get("seq")
               and existing[i].get("type") == events[i].get("type")
               for i in range(len(events))):
        return "diverged", extra
    return ("same" if extra == 0 else "continued"), extra


def backup_session_file(path: Path) -> Path:
    """Keep a timestamped copy of a session log before replacing it."""
    dest = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(path, dest)
    return dest


def zstd_frame(raw: bytes, level: int = 9) -> bytes:
    """Compress one independent, checksummed Zstandard frame."""
    exe = shutil.which("zstd")
    if exe:
        proc = subprocess.run(
            [exe, "-q", "--check", f"-{level}", "-c"],
            input=raw,
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        raise SystemExit(f"zstd failed: {proc.stderr.decode(errors='replace')}")
    # fallback: Node 24 exposes zstd in zlib (checksummed by default)
    node = shutil.which("node")
    if not node:
        raise SystemExit("need either the `zstd` CLI or `node` on PATH")
    script = (
        "const fs=require('fs'),z=require('zlib');"
        "let b=[];process.stdin.on('data',c=>b.push(c)).on('end',()=>{"
        "process.stdout.write(z.zstdCompressSync(Buffer.concat(b)));});"
    )
    proc = subprocess.run([node, "-e", script], input=raw, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"node zstd failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout


def write_session_file(header: dict, events: list[dict], dest: Path, level: int = 9) -> bytes:
    """Write a DSH v4 session log.

    DSH requires the *first* Zstandard frame to hold exactly the header line
    (``assertZstdHeaderFrame``), then one frame per durable append batch; the
    header and the first batch must not share a frame.
    """
    dumps = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
    header_line = (dumps(header) + "\n").encode("utf-8")
    body = "".join(dumps(ev) + "\n" for ev in events).encode("utf-8")
    blob = zstd_frame(header_line, level) + zstd_frame(body, level)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, dest)
    return header_line + body


# --------------------------------------------------------------------------
# verification: the invariants DSH itself enforces when it reads a log back
# --------------------------------------------------------------------------
ZSTD_MAGIC = 4247762216  # 0xFD2FB528, from DSH's zstd frame scanner


def scan_frames(blob: bytes):
    """Port of ``scanZstdFrames``: complete frame ranges + torn-tail offset."""
    frames = []
    off = 0
    while off < len(blob):
        start = off
        if len(blob) - off < 4:
            return frames, start
        if int.from_bytes(blob[off:off + 4], "little") != ZSTD_MAGIC:
            raise ValueError(f"invalid frame magic at byte {off}")
        off += 4
        if off == len(blob):
            return frames, start
        descriptor = blob[off]
        off += 1
        if descriptor & 24:
            raise ValueError(f"reserved frame-header bit at byte {off - 1}")
        fcs_flag = descriptor >> 6
        single = bool(descriptor & 32)
        checksum = bool(descriptor & 4)
        did = descriptor & 3
        off += (0 if single else 1) + (4 if did == 3 else did)
        off += (1 if single else 0) if fcs_flag == 0 else 1 << fcs_flag
        if len(blob) - off < 0:
            return frames, start
        while True:
            if len(blob) - off < 3:
                return frames, start
            bh = int.from_bytes(blob[off:off + 3], "little")
            off += 3
            last, btype, bsize = bh & 1, (bh >> 1) & 3, bh >> 3
            if btype == 3:
                raise ValueError(f"reserved block type at byte {off - 3}")
            off += 1 if btype == 1 else bsize
            if last:
                break
        if len(blob) - off < (4 if checksum else 0):
            return frames, start
        if checksum:
            off += 4
        frames.append((start, off - start, checksum))
    return frames, None


def _decompress(blob: bytes) -> bytes:
    proc = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.decode(errors="replace").strip()[:160])
    return proc.stdout


def _assert_message_shape(event: dict, problems: list[str]):
    """Port of ``assertMessageEventShape`` from @deepseek-ai/dsh-session."""
    etype = event.get("type")
    roles = {"system/message": "system", "developer/message": "developer",
             "user/message": "user", "assistant/message": "assistant",
             "tool/result": "tool"}
    if etype not in roles:
        return
    data = event.get("data") or {}
    message = data if etype == "user/message" else data.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not message["id"]:
        problems.append(f"seq {event.get('seq')}: {etype} lacks an identified message")
        return
    if message.get("role") != roles[etype]:
        problems.append(f"seq {event.get('seq')}: {etype} message role must be {roles[etype]}")
    source = message.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or not source["kind"]:
        problems.append(f"seq {event.get('seq')}: {etype} message has invalid source")
        return
    if not isinstance(message.get("content"), list):
        problems.append(f"seq {event.get('seq')}: {etype} message has invalid content")
    if etype == "system/message" and source["kind"] != "system-prompt":
        problems.append(f"seq {event.get('seq')}: system/message needs system-prompt source")
    if etype == "assistant/message":
        if source["kind"] != "model":
            problems.append(f"seq {event.get('seq')}: assistant/message needs model source")
        elif not (isinstance(source.get("provider"), str) and source["provider"]
                  and isinstance(source.get("model"), str) and source["model"]):
            problems.append(f"seq {event.get('seq')}: assistant/message needs provider/model")
    if etype == "tool/result":
        call_id = source.get("callId")
        if source["kind"] != "tool" or not isinstance(call_id, str) or not call_id:
            problems.append(f"seq {event.get('seq')}: tool/result needs tool source")
        elif message.get("toolCallId") != call_id:
            problems.append(f"seq {event.get('seq')}: tool/result mismatched call ids")


# Surface events must declare how they join the conversation surface:
# the literal "append", or a replacement-range object. Omitting it fails the
# read with "<type> surfaceOp requires an object".
SURFACE_TYPES = ("system/message", "user/message", "developer/message",
                 "assistant/message", "tool/result")


def _assert_surface_op(event: dict, problems: list[str]):
    """Port of ``foldSurface`` from the v3→v4 codec."""
    if event.get("type") not in SURFACE_TYPES:
        return
    op = event.get("surfaceOp")
    if op == "append":
        return
    if isinstance(op, dict) and {"startSeq", "endSeq"} <= set(op):
        return
    problems.append(
        f"seq {event.get('seq')}: {event.get('type')} surfaceOp must be \"append\" "
        f"or a replacement range object (got {op!r})"
    )


def verify_session_bytes(blob: bytes, expected_id: str | None = None,
                         workspace: str | None = None) -> list[str]:
    """Return the list of violations of DSH's own session-log invariants."""
    problems: list[str] = []
    try:
        frames, torn = scan_frames(blob)
    except ValueError as exc:
        return [f"frame scan: {exc}"]
    if torn is not None:
        problems.append("incomplete final frame")
    if not frames:
        return ["empty log"]
    plains = []
    for index, (start, length, checksum) in enumerate(frames):
        if not checksum:
            problems.append(f"frame {index} has no content checksum")
        try:
            plains.append(_decompress(blob[start:start + length]))
        except ValueError as exc:
            problems.append(f"frame {index}: {exc}")
            return problems
    first = plains[0]
    if not first or first.index(b"\n") != len(first) - 1:
        problems.append("first frame is not exactly one header line")
    rows = []
    for plain in plains:
        for line in plain.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    problems.append(f"unparsable row: {exc}")
    if not rows:
        return problems + ["no rows"]

    header, events = rows[0], rows[1:]
    if header.get("type") != "session" or header.get("version") != 4:
        problems.append("bad session header")
    if expected_id and header.get("id") != expected_id:
        problems.append(f"header id {header.get('id')!r} != {expected_id!r}")
    if not isinstance(header.get("createdAt"), int) or header["createdAt"] < 0:
        problems.append("bad createdAt")
    if workspace and header.get("cwd") != workspace:
        problems.append(f"header cwd {header.get('cwd')!r} != {workspace!r}")
    if not isinstance(header.get("isSeeded"), bool):
        problems.append("isSeeded must be a boolean")
    allowed_header = {"type", "version", "id", "createdAt", "isSeeded", "delegationDepth",
                      "cwd", "parentSession", "origin", "agentPreset"}
    extra = sorted(set(header) - allowed_header)
    if extra:
        problems.append(f"header has unexpected field(s) {extra}")
    for key in ("version", "id", "createdAt", "isSeeded", "delegationDepth"):
        if key not in header:
            problems.append(f"header lacks required field {key}")

    if [e.get("seq") for e in events] != list(range(len(events))):
        problems.append("seq values are not contiguous from 0")
    if any(events[i]["time"] < events[i - 1]["time"] for i in range(1, len(events))):
        problems.append("timestamps are not monotonic")

    turn_open = step_open = False
    calls: dict[str, int] = {}
    for event in events:
        etype = event.get("type")
        seq = event.get("seq")
        _assert_message_shape(event, problems)
        _assert_surface_op(event, problems)
        if etype == "turn/start":
            if turn_open:
                problems.append(f"seq {seq}: nested turn/start")
            turn_open = True
        elif etype == "turn/end":
            if not turn_open or step_open:
                problems.append(f"seq {seq}: turn/end without open step/turn")
            turn_open = False
        elif etype == "step/start":
            if step_open:
                problems.append(f"seq {seq}: nested step/start")
            step_open = True
        elif etype == "step/end":
            if not step_open:
                problems.append(f"seq {seq}: step/end without step/start")
            step_open = False
        elif etype in ("user/message", "assistant/message", "tool/call", "tool/result"):
            if not (turn_open and step_open):
                problems.append(f"seq {seq}: {etype} outside an open turn/step")
        if etype == "tool/call":
            calls[event["data"]["callId"]] = seq
        elif etype == "tool/result":
            call_id = event["data"]["message"]["toolCallId"]
            if calls.get(call_id) != (event.get("sourceEventSeqs") or [None])[0]:
                problems.append(f"seq {seq}: bad sourceEventSeqs for {call_id}")
        elif etype in ("session/title", "session/title-llm-request"):
            refs = event["data"].get("messageSeqs") or []
            kind = (event["data"].get("source") or {}).get("kind")
            if (len(refs) == 0) != (kind == "user"):
                problems.append(f"seq {seq}: title messageSeqs/kind mismatch")
            for ref in refs:
                target = events[ref] if isinstance(ref, int) and 0 <= ref < len(events) else None
                if (target is None or target.get("type") != "user/message"
                        or (target["data"].get("source") or {}).get("kind") != "user"):
                    problems.append(f"seq {seq}: title cites non-human message {ref}")
    if turn_open or step_open:
        problems.append("log ends with an open turn/step")

    blocks = [b["id"] for e in events if e.get("type") == "assistant/message"
              for b in e["data"]["message"]["content"] if b.get("type") == "tool-call"]
    if sorted(blocks) != sorted(calls):
        problems.append(f"{len(blocks)} tool-call blocks vs {len(calls)} tool/call records")
    return problems


# --------------------------------------------------------------------------
# DSH workspace registration
# --------------------------------------------------------------------------
def register_in_workspace(workspace_json: Path, workspace: str, session_ids: list[str],
                          backup: bool = True) -> dict:
    data = json.loads(workspace_json.read_text())
    table = data["tables"]["workspaces"]
    target = next((w for w in table.values() if w.get("path") == workspace), None)
    created = False
    if target is None:
        wid = str(uuid.uuid4())
        target = {
            "path": workspace,
            "title": os.path.basename(workspace.rstrip(os.sep)),
            "sessionIds": [],
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z",
        }
        table[wid] = target
        data["global"].setdefault("workspaceIds", []).append(wid)
        created = True

    existing = list(target.get("sessionIds") or [])
    added = [sid for sid in session_ids if sid not in existing]
    if added:
        target["sessionIds"] = existing + added
        target["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
        if backup and workspace_json.exists():
            bak = workspace_json.with_name(
                f"{workspace_json.name}.bak-zcode-import-{now_ms()}"
            )
            shutil.copy2(workspace_json, bak)
        workspace_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"created_workspace": created, "added": added, "total": len(target["sessionIds"])}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def reference_system_content(dsh_home: Path, workspace: str, explicit: Path | None):
    """Reuse a real DSH system prompt so imported turns stay well formed."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    else:
        current = os.environ.get("DSH_SESSION_ID")
        ws_dir = find_existing_workspace_dir(dsh_home, workspace) or (
            dsh_home / "sessions" / workspace_dir_name(workspace)
        )
        if current:
            candidates.append(ws_dir / current / "session.v4.jsonl.zstd")
        if ws_dir.is_dir():
            found = sorted(ws_dir.glob("*/session.v4.jsonl.zstd"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            candidates.extend(found)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = subprocess.run(["zstd", "-dc", str(path)], capture_output=True).stdout
        except OSError:
            continue
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "system/message":
                content = ((rec.get("data") or {}).get("message") or {}).get("content")
                if content:
                    return content
    return [{"type": "text", "text": "You are an AI agent powered by DeepSeek Harness."}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=os.getcwd(), help="workspace path to import")
    ap.add_argument("--db", default="~/.zcode/cli/db/db.sqlite", help="ZCode SQLite path")
    ap.add_argument("--dsh-home", default=os.environ.get("DSH_HOME", "~/.dsh"))
    ap.add_argument("--artifacts", default="~/.zcode/cli/artifacts")
    ap.add_argument("--out", help="staging directory (default: DSH session dir)")
    ap.add_argument("--apply", action="store_true",
                    help="write into DSH home and register in workspace.json")
    ap.add_argument("--no-attachments", action="store_true",
                    help="do not copy images into the DSH attachment store")
    ap.add_argument("--no-system-message", action="store_true")
    ap.add_argument("--system-from", help="session.v4.jsonl.zstd to copy the system prompt from")
    ap.add_argument("--force", action="store_true",
                    help="rewrite existing session files (a backup is always kept)")
    ap.add_argument("--overwrite-continued", action="store_true",
                    help="also overwrite a session the Harness has continued; "
                         "this CORRUPTS it if DSH currently holds the session")
    ap.add_argument("--session", action="append", help="only these ZCode session ids")
    ap.add_argument("--include-subdirs", action="store_true",
                    help="also import sessions ZCode ran from subdirectories")
    ap.add_argument("--list", action="store_true", help="list matching sessions and exit")
    args = ap.parse_args(argv)

    workspace = os.path.realpath(os.path.expanduser(args.workspace))
    db_path = Path(os.path.expanduser(args.db))
    dsh_home = Path(os.path.expanduser(args.dsh_home))
    artifacts_root = Path(os.path.expanduser(args.artifacts))

    conn = open_zcode_db(db_path)
    sessions = load_sessions(conn, workspace, descendants=args.include_subdirs)
    if args.session:
        wanted = set(args.session)
        sessions = [s for s in sessions if s["id"] in wanted]
    if args.list:
        for s in sessions:
            where = s["directory"] if s["directory"] != workspace else ""
            print(f"{s['id']}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(s['time_created']/1000))}  "
                  f"{s['title']}  {where}")
        return 0
    if not sessions:
        print(f"no ZCode sessions found for {workspace}")
        return 0

    if args.no_system_message:
        system_content = None
    else:
        system_content = reference_system_content(
            dsh_home, workspace,
            Path(args.system_from).expanduser() if args.system_from else None,
        )

    staging = Path(args.out).expanduser() if args.out else None
    store = AttachmentStore(dsh_home, artifacts_root,
                            enabled=args.apply and not args.no_attachments)

    written, skipped, failed, blocked = [], [], [], []
    total_stats = {}
    for s in sessions:
        dsh_id = "session-" + det_uuid("zcode-session", s["id"])
        # Each log lives in the session directory DSH derives from its own cwd.
        cwd = s["directory"]
        out_root = staging or find_existing_workspace_dir(dsh_home, cwd) or (
            dsh_home / "sessions" / workspace_dir_name(cwd)
        )
        target_dir = out_root / dsh_id
        target = target_dir / "session.v4.jsonl.zstd"
        try:
            messages = load_messages(conn, s["id"])
            parts = load_parts(conn, s["id"])
            builder = SessionBuilder(s, cwd, dsh_id, system_content, store)
            header, events = builder.build(messages, parts)
            if not events:
                skipped.append((s["id"], dsh_id))
                continue

            backup = None
            if target.exists():
                state, extra = inspect_existing(target, events)
                if not args.force:
                    skipped.append((s["id"], dsh_id))
                    continue
                if state == "continued" and not args.overwrite_continued:
                    # Writing here would leave the Harness's own seq counter
                    # ahead of the file and corrupt the log.
                    blocked.append((s["id"], dsh_id, extra))
                    continue
                backup = backup_session_file(target)

            raw = write_session_file(header, events, target)
            problems = verify_session_bytes(target.read_bytes(), expected_id=dsh_id,
                                            workspace=cwd)
            if args.apply and store.enabled:
                problems += check_attachments(events, store.objects)
            if problems:
                target.unlink(missing_ok=True)
                if backup is not None:
                    shutil.copy2(backup, target)
                failed.append((s["id"], "verification: " + "; ".join(problems[:3])))
                continue
            if args.apply:
                (target_dir / "session.lock").touch(exist_ok=True)
            written.append((s, dsh_id, len(raw), builder.stats))
            for k, v in builder.stats.items():
                total_stats[k] = total_stats.get(k, 0) + v
        except Exception as exc:  # keep going; report at the end
            failed.append((s["id"], repr(exc)))

    print(f"workspace : {workspace}")
    print(f"zcode db  : {db_path}  ({len(sessions)} session(s) matched"
          f"{', including subdirectories' if args.include_subdirs else ''})")
    print(f"target    : {staging or dsh_home / 'sessions'}"
          f"{'' if args.apply else '   [staging / dry-run]'}")
    print()
    for s, dsh_id, size, stats in written:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["time_created"] / 1000))
        where = "" if s["directory"] == workspace else f"   [{s['directory']}]"
        print(f"  + {when}  {s['title'][:60]}{where}")
        print(f"      {s['id']} -> {dsh_id}  ({size/1024:.0f} KiB, "
              f"{stats['user']} user / {stats['assistant']} assistant / {stats['tool']} tool"
              f"{', ' + str(stats['tool_error']) + ' failed' if stats['tool_error'] else ''}"
              f"{', ' + str(stats['images']) + ' image(s)' if stats['images'] else ''})")
    for zid, dsh_id in skipped:
        print(f"  = skipped (already imported): {zid} -> {dsh_id}")
    for zid, dsh_id, extra in blocked:
        print(f"  ! REFUSED (continued in DSH, +{extra} live event(s)): {zid} -> {dsh_id}")
    for zid, err in failed:
        print(f"  ! FAILED {zid}: {err}")
    print()
    print(f"totals: {len(written)} written, {len(skipped)} skipped, "
          f"{len(blocked)} refused, {len(failed)} failed")
    if blocked:
        print("        a session the Harness continued must be re-imported only with\n"
              "        --overwrite-continued AND with DSH closed, or not at all")
    if total_stats:
        print("        " + ", ".join(f"{k}={v}" for k, v in total_stats.items()))
    if store.copied or store.missing or store.undecodable:
        print(f"images: {store.copied} copied into DSH attachment store, "
              f"{store.missing} artifact(s) not found, "
              f"{store.undecodable} not decodable (kept as text only)")

    if args.apply and written:
        ws_json = dsh_home / "storages" / "workspace.json"
        if ws_json.exists():
            info = register_in_workspace(ws_json, workspace, [d for _, d, _, _ in written])
            print(f"workspace.json: +{len(info['added'])} session(s) registered "
                  f"(workspace total {info['total']})")
        else:
            print(f"! {ws_json} not found - sessions are on disk but not registered")
    elif written:
        print("dry run: nothing written outside the staging directory")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())