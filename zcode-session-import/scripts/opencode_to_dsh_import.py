#!/usr/bin/env python3
"""Import opencode v2 sessions into DeepSeek Harness (DSH) session logs.

Why this exists alongside ``zcode_to_dsh_import.py``
---------------------------------------------------
The ZCode importer only knows ZCode's SQLite store. Projects whose history ran
in *opencode* instead have no ZCode rows at all, so importing them via ZCode
would require writing into ZCode's database first. This script goes straight
from opencode to DSH and leaves ZCode completely untouched.

It reuses the ZCode importer's proven DSH-side machinery -- Zstandard framing,
the fast self-verifier, workspace registration and the system-prompt reference
-- and only replaces the source-side translation.

Source shape (opencode v2, ``~/.local/share/opencode/opencode.db``)
------------------------------------------------------------------
``session_message(id, session_id, type, seq, time_created, data)`` is the
conversation as an event stream ordered by ``seq``:

* ``user``   -- ``{text, time:{created}}``; a user prompt closes the previous
  turn and opens the next one.
* ``assistant`` -- ``{model:{providerID,id}, content:[...], finish, time:{created,completed}}``.
  Each assistant row is one *step* of the current turn. ``content`` entries are
  ``reasoning`` / ``text`` blocks and ``tool`` blocks
  ``{id, name, state:{status,input,content,metadata}, time}``.
* ``system`` / ``synthetic`` -- runtime notes delivered ahead of a model call.
  They are buffered and emitted immediately after the next ``step/start``, the
  same place ZCode's ``todo_reminder`` rows go.

Read-only: the opencode database is opened with ``mode=ro`` and never written.

Usage
-----
    # preview (writes nothing outside --out)
    python3 opencode_to_dsh_import.py --workspace "$PWD" --out ./_oc_import

    # for real (writes into $DSH_HOME and registers in workspace.json)
    python3 opencode_to_dsh_import.py --workspace "$PWD" --apply

Then always validate with the Harness's own reader:

    node validate_session_log.mjs <staged-or-installed-file>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zcode_to_dsh_import import (  # noqa: E402
    backup_session_file,
    det_uuid,
    encode_text,
    find_existing_workspace_dir,
    inspect_existing,
    now_ms,
    reference_system_content,
    register_in_workspace,
    verify_session_bytes,
    workspace_dir_name,
    write_session_file,
)

DEFAULT_DB = "~/.local/share/opencode/opencode.db"

# Runtime notes are injected into a step, not spoken by the user.
RUNTIME_SOURCE_KIND = "opencode-agent-runtime"


# --------------------------------------------------------------------------
# opencode side (read-only)
# --------------------------------------------------------------------------
def open_opencode_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise SystemExit(f"opencode database not found: {db_path}")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.execute("select 1").fetchone()
        return conn
    except sqlite3.Error:
        # immutable=1 ignores the WAL, so only fall back when mode=ro fails.
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        conn.execute("select 1").fetchone()
        return conn


def load_sessions(conn: sqlite3.Connection, workspace: str,
                  descendants: bool = False) -> list[dict]:
    conn.row_factory = sqlite3.Row
    if descendants:
        rows = conn.execute(
            "select id, directory, title, time_created, time_updated, agent, model "
            "from session where directory = ? or directory like ? "
            "order by time_created",
            (workspace, workspace.rstrip(os.sep) + os.sep + "%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "select id, directory, title, time_created, time_updated, agent, model "
            "from session where directory = ? order by time_created",
            (workspace,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_rows(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """The conversation event stream, oldest first."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select id, type, seq, time_created, data from session_message "
        "where session_id = ? order by seq",
        (session_id,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["data"]) if r["data"] else {}
        except json.JSONDecodeError:
            payload = {}
        out.append({"id": r["id"], "type": r["type"], "seq": r["seq"],
                    "time_created": r["time_created"], "data": payload})
    return out


# --------------------------------------------------------------------------
# translation
# --------------------------------------------------------------------------
def row_time(row: dict, key: str = "created") -> int:
    t = (row.get("data") or {}).get("time") or {}
    for k in (key, "created", "completed"):
        val = t.get(k)
        if val is not None:
            return int(val)
    return int(row.get("time_created") or now_ms())


def text_blocks(content) -> list[dict]:
    """Tool output -> DSH content blocks (text only, never silently dropped)."""
    blocks: list[dict] = []
    if isinstance(content, str):
        return [{"type": "text", "text": encode_text(content)}]
    for item in content or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "text":
            text = item.get("text") or ""
            if text.strip():
                blocks.append({"type": "text", "text": encode_text(text)})
        elif itype in ("image", "file"):
            # No attachment bytes are reachable from this store; keep the marker
            # the model actually saw instead of emitting a broken image block.
            name = item.get("filename") or item.get("name") or "attachment"
            blocks.append({"type": "text",
                           "text": f"[Attached {itype}: {name}]"})
        elif itype == "reasoning":
            continue
        else:
            text = item.get("text")
            if text:
                blocks.append({"type": "text", "text": encode_text(str(text))})
    return blocks


class OpenCodeBuilder:
    """Turn one opencode event stream into a DSH v4 event list."""

    def __init__(self, session: dict, cwd: str, dsh_session_id: str,
                 system_content: list | None):
        self.session = session
        self.sid = session["id"]
        self.cwd = cwd
        self.dsh_session_id = dsh_session_id
        self.system_content = system_content
        self.events: list[dict] = []
        self.seq = -1
        self.last_time = int(session["time_created"])
        self.turn = 0
        self.step = 0
        self.step_open = False
        self.pending_injected: list[tuple[int, dict]] = []
        self.first_user_seq: int | None = None
        self.first_user_text = ""
        self.stats = {"user": 0, "assistant": 0, "tool": 0, "tool_error": 0,
                      "reasoning": 0, "injected": 0, "skipped": 0}

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
        pending, self.pending_injected = self.pending_injected, []
        for when, data in pending:
            self.emit("user/message", data, when, surfaceOp="append")
            self.stats["injected"] += 1

    def close_step(self, when: int):
        if not self.step_open:
            return
        self.emit("step/end", {"turn": self.turn, "step": self.step}, when)
        self.step_open = False

    def message_id(self, tag: str, key) -> str:
        return det_uuid("opencode-message", self.sid, tag, str(key))

    # -- handlers ----------------------------------------------------------
    def add_user_prompt(self, row: dict):
        created = row_time(row, "created")
        text = (row["data"].get("text") or "").strip()
        if not text:
            self.stats["skipped"] += 1
            return
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
            self.emit("system/message", {
                "turn": self.turn,
                "step": self.step,
                "message": {
                    "role": "system",
                    "content": self.system_content,
                    "source": {"kind": "system-prompt"},
                    "id": self.message_id("system", f"{self.turn}"),
                },
            }, created, surfaceOp="append")
        u_seq = self.emit("user/message", {
            "content": [{"type": "text", "text": encode_text(text)}],
            "source": {"kind": "user", "importedFrom": "opencode"},
            "role": "user",
            "id": self.message_id("user", row["id"]),
        }, created, surfaceOp="append")
        self.stats["user"] += 1
        if self.first_user_seq is None:
            self.first_user_seq = u_seq
            self.first_user_text = text

    def add_injected(self, row: dict):
        text = (row["data"].get("text") or "").strip()
        if not text:
            self.stats["skipped"] += 1
            return
        # Delivered ahead of a model call -> belongs inside the step it entered.
        self.pending_injected.append((row_time(row, "created"), {
            "content": [{"type": "text", "text": encode_text(text)}],
            "source": {"kind": RUNTIME_SOURCE_KIND, "form": "system_reminder",
                       "importedFrom": "opencode"},
            "role": "user",
            "id": self.message_id("reminder", row["id"]),
        }))

    def add_assistant(self, row: dict):
        content = row["data"].get("content") or []
        blocks: list[dict] = []
        tool_parts: list[dict] = []
        for part in content:
            ptype = part.get("type")
            if ptype == "reasoning":
                text = (part.get("text") or "").strip()
                if text:
                    blocks.append({"type": "reasoning", "text": encode_text(text)})
                    self.stats["reasoning"] += 1
            elif ptype == "text":
                text = part.get("text") or ""
                if text.strip():
                    blocks.append({"type": "text", "text": encode_text(text)})
            elif ptype == "tool":
                state = part.get("state") or {}
                blocks.append({
                    "type": "tool-call",
                    "id": part.get("id") or det_uuid("call", self.sid, str(row["seq"])),
                    "name": part.get("name") or "tool",
                    "arguments": json.dumps(state.get("input") or {},
                                            ensure_ascii=False),
                })
                tool_parts.append(part)
        if not blocks:
            # Aborted / contentless rows carry no conversation.
            self.stats["skipped"] += 1
            return

        created = row_time(row, "created")
        completed = row_time(row, "completed")
        if not self.step_open:
            self.open_step(created)

        model = row["data"].get("model") or {}
        provider = (model.get("providerID") or model.get("provider")
                    or "opencode")
        model_id = model.get("id") or model.get("modelID") or "unknown"
        self.emit("assistant/message", {
            "turn": self.turn,
            "step": self.step,
            "stream": [],
            "message": {
                "role": "assistant",
                "content": blocks,
                "source": {"kind": "model", "provider": provider,
                           "model": model_id},
                "id": self.message_id("assistant", row["id"]),
            },
        }, created, surfaceOp="append")
        self.stats["assistant"] += 1

        for part in tool_parts:
            self.add_tool(part, row)

        self.close_step(completed)

    def add_tool(self, part: dict, row: dict):
        state = part.get("state") or {}
        call_id = part.get("id") or det_uuid("call", self.sid, str(row["seq"]))
        name = part.get("name") or "tool"
        args = json.dumps(state.get("input") or {}, ensure_ascii=False)
        t_start = int((part.get("time") or {}).get("created") or row_time(row, "created"))
        t_end = int((part.get("time") or {}).get("completed")
                    or (part.get("time") or {}).get("created")
                    or row_time(row, "completed"))

        call_seq = self.emit("tool/call", {
            "turn": self.turn,
            "step": self.step,
            "callId": call_id,
            "name": name,
            "arguments": args,
        }, t_start)

        is_error = state.get("status") == "error"
        blocks = text_blocks(state.get("content"))
        if not blocks:
            fallback = (state.get("metadata") or {}).get("output")
            if fallback:
                blocks = [{"type": "text", "text": encode_text(fallback)}]
            elif is_error and state.get("error"):
                blocks = [{"type": "text", "text": encode_text(str(state["error"]))}]
        self.emit("tool/result", {
            "turn": self.turn,
            "step": self.step,
            "message": {
                "role": "tool",
                "source": {"kind": "tool", "callId": call_id},
                "toolCallId": call_id,
                "content": blocks,
                "isError": bool(is_error),
                "id": self.message_id("result", f"{row['id']}:{call_id}"),
            },
        }, t_end, surfaceOp="append", sourceEventSeqs=[call_seq])
        self.stats["tool"] += 1
        if is_error:
            self.stats["tool_error"] += 1

    # -- driver ------------------------------------------------------------
    def build(self, rows: list[dict]) -> tuple[dict, list[dict]]:
        created = int(self.session["time_created"])
        self.emit("permission/preset", {"preset": "workspace-write"}, created)
        self.emit("sandbox/mode", {"mode": "workspace-write"}, created)
        self.emit("approval/policy", {"policy": "ask"}, created)

        for row in rows:
            rtype = row["type"]
            if rtype == "user":
                self.add_user_prompt(row)
            elif rtype == "assistant":
                self.add_assistant(row)
            elif rtype in ("system", "synthetic"):
                self.add_injected(row)
            else:
                # idle / model-switched / unknown: no conversation content.
                self.stats["skipped"] += 1

        if self.turn == 0:
            return {}, []

        # A trailing runtime note never got a following model call; give it the
        # final turn's last step so it is still recorded.
        if self.pending_injected:
            self.open_step(self.last_time)
            self.flush_injected()

        self.close_step(self.last_time)
        self.emit("turn/end",
                  {"turn": self.turn, "reason": {"kind": "completed"}},
                  self.last_time)

        title = (self.session.get("title") or "").strip()
        if title:
            self.emit("session/title",
                      {"title": title, "messageSeqs": [],
                       "source": {"kind": "user"}}, self.last_time)
        else:
            fallback = " ".join(self.first_user_text.split())[:60] or "Imported session"
            self.emit("session/title",
                      {"title": fallback,
                       "messageSeqs": [self.first_user_seq] if self.first_user_seq is not None else [],
                       "source": {"kind": "fallback"}}, self.last_time)
        self.emit("session/end-seed", {}, self.last_time)

        header = {
            "type": "session",
            "version": 4,
            "id": self.dsh_session_id,
            "createdAt": created,
            "cwd": self.cwd,
            "isSeeded": False,
            "delegationDepth": 0,
            "agentPreset": "standard",
        }
        return header, self.events


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=os.getcwd(),
                    help="workspace path to import")
    ap.add_argument("--db", default=DEFAULT_DB, help="opencode SQLite path")
    ap.add_argument("--dsh-home", default=os.environ.get("DSH_HOME", "~/.dsh"))
    ap.add_argument("--out", help="staging directory (default: DSH session dir)")
    ap.add_argument("--apply", action="store_true",
                    help="write into DSH home and register in workspace.json")
    ap.add_argument("--force", action="store_true",
                    help="rewrite existing session files (a backup is always kept)")
    ap.add_argument("--overwrite-continued", action="store_true",
                    help="also overwrite a session the Harness has continued; "
                         "this CORRUPTS it if DSH currently holds the session")
    ap.add_argument("--no-system-message", action="store_true")
    ap.add_argument("--system-from",
                    help="session.v4.jsonl.zstd to copy the system prompt from")
    ap.add_argument("--session", action="append",
                    help="only these opencode session ids")
    ap.add_argument("--include-subdirs", action="store_true",
                    help="also import sessions opencode ran from subdirectories")
    ap.add_argument("--list", action="store_true",
                    help="list matching sessions and exit")
    args = ap.parse_args(argv)

    workspace = os.path.realpath(os.path.expanduser(args.workspace))
    db_path = Path(os.path.expanduser(args.db))
    dsh_home = Path(os.path.expanduser(args.dsh_home))

    conn = open_opencode_db(db_path)
    sessions = load_sessions(conn, workspace, descendants=args.include_subdirs)
    if args.session:
        wanted = set(args.session)
        sessions = [s for s in sessions if s["id"] in wanted]
    if args.list:
        for s in sessions:
            where = s["directory"] if s["directory"] != workspace else ""
            print(f"{s['id']}  "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(s['time_created']/1000))}  "
                  f"{s['title']}  {where}")
        return 0
    if not sessions:
        print(f"no opencode sessions found for {workspace}")
        return 0

    if args.no_system_message:
        system_content = None
    else:
        system_content = reference_system_content(
            dsh_home, workspace,
            Path(args.system_from).expanduser() if args.system_from else None,
        )

    staging = Path(args.out).expanduser() if args.out else None

    written, skipped, failed, blocked = [], [], [], []
    total_stats: dict[str, int] = {}
    for s in sessions:
        dsh_id = "session-" + det_uuid("opencode-session", s["id"])
        cwd = s["directory"]
        out_root = staging or find_existing_workspace_dir(dsh_home, cwd) or (
            dsh_home / "sessions" / workspace_dir_name(cwd)
        )
        target_dir = out_root / dsh_id
        target = target_dir / "session.v4.jsonl.zstd"
        try:
            rows = load_rows(conn, s["id"])
            if not rows:
                skipped.append((s["id"], dsh_id, "no rows"))
                continue
            builder = OpenCodeBuilder(s, cwd, dsh_id, system_content)
            header, events = builder.build(rows)
            if not events:
                skipped.append((s["id"], dsh_id, "nothing to import"))
                continue

            backup = None
            if target.exists():
                state, extra = inspect_existing(target, events)
                if not args.force:
                    skipped.append((s["id"], dsh_id, "already imported"))
                    continue
                if state == "continued" and not args.overwrite_continued:
                    blocked.append((s["id"], dsh_id, extra))
                    continue
                backup = backup_session_file(target)

            raw = write_session_file(header, events, target)
            problems = verify_session_bytes(target.read_bytes(), expected_id=dsh_id,
                                            workspace=cwd)
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

    print(f"workspace  : {workspace}")
    print(f"opencode db: {db_path}  ({len(sessions)} session(s) matched"
          f"{', including subdirectories' if args.include_subdirs else ''})")
    print(f"target     : {staging or dsh_home / 'sessions'}"
          f"{'' if args.apply else '   [staging / dry-run]'}")
    print()
    for s, dsh_id, size, stats in written:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["time_created"] / 1000))
        where = "" if s["directory"] == workspace else f"   [{s['directory']}]"
        print(f"  + {when}  {s['title'][:60]}{where}")
        print(f"      {s['id']} -> {dsh_id}  ({size/1024:.0f} KiB, "
              f"{stats['user']} user / {stats['assistant']} assistant / "
              f"{stats['tool']} tool"
              f"{', ' + str(stats['tool_error']) + ' failed' if stats['tool_error'] else ''}"
              f"{', ' + str(stats['injected']) + ' runtime note(s)' if stats['injected'] else ''})")
    for sid, dsh_id, why in skipped:
        print(f"  = skipped ({why}): {sid} -> {dsh_id}")
    for sid, dsh_id, extra in blocked:
        print(f"  ! REFUSED (continued in DSH, +{extra} live event(s)): {sid} -> {dsh_id}")
    for sid, err in failed:
        print(f"  ! FAILED {sid}: {err}")
    print()
    print(f"totals: {len(written)} written, {len(skipped)} skipped, "
          f"{len(blocked)} refused, {len(failed)} failed")
    if blocked:
        print("        a session the Harness continued must be re-imported only with\n"
              "        --overwrite-continued AND with DSH closed, or not at all")
    if total_stats:
        print("        " + ", ".join(f"{k}={v}" for k, v in total_stats.items()))

    if args.apply and written:
        ws_json = dsh_home / "storages" / "workspace.json"
        if ws_json.exists():
            info = register_in_workspace(ws_json, workspace,
                                         [d for _, d, _, _ in written])
            print(f"workspace.json: +{len(info['added'])} session(s) registered "
                  f"(workspace total {info['total']})")
        else:
            print(f"! {ws_json} not found - sessions are on disk but not registered")
    elif written:
        print("dry run: nothing written outside the staging directory")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
