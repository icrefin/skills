#!/usr/bin/env node
/**
 * Validate a DSH session log with DeepSeek Harness's own reader.
 *
 * Instead of re-implementing the format rules (which is how two imports were
 * accepted locally but rejected by the Harness), this lifts the real validation
 * code out of the installed `app.asar` and runs it against the file:
 * `restoreReleasedV4Artifact` from @deepseek-ai/dsh-session-format-v3-to-v4,
 * seeded with the build's own known-event-type set.
 *
 * Usage:
 *   node validate_session_log.mjs <session.v4.jsonl.zstd | .jsonl> [--asar PATH]
 *
 * Exits 0 when the log is accepted, 1 otherwise. The extracted validator is
 * cached in the system temp directory, so repeat runs are cheap.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import zlib from 'node:zlib';

const DEFAULT_ASAR = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar';
const SCOPE = 'node_modules/@deepseek-ai';
const SEEDS = ['dsh-session-format-v3-to-v4'];
const CODE = /\.(js|mjs|cjs)$/;

// ---------------------------------------------------------------- asar ----
function readAsar(asarPath) {
  const buf = fs.readFileSync(asarPath);
  const headerSize = buf.readUInt32LE(12);
  const header = JSON.parse(buf.subarray(16, 16 + headerSize).toString('utf8'));
  const entries = new Map();
  (function walk(node, prefix) {
    for (const [name, value] of Object.entries(node.files ?? {})) {
      const full = `${prefix}/${name}`;
      if (value.files) walk(value, full);
      else entries.set(full, { offset: Number(value.offset), size: value.size });
    }
  })(header, '');
  // The data section starts after the JSON header plus alignment padding; find
  // it by looking for the byte the first known file must begin with.
  const probe = entries.get('/dsh/package.json') ?? entries.get('/dsh/node_modules/@deepseek-ai/dsh-session/package.json');
  let base = null;
  if (probe) {
    for (let pad = 0; pad <= 16; pad += 1) {
      const candidate = 16 + headerSize + pad;
      if (buf.subarray(candidate + probe.offset, candidate + probe.offset + 1).toString() === '{') {
        base = candidate;
        break;
      }
    }
  }
  if (base === null) base = 16 + headerSize + 2; // observed layout of the 0.2.x bundle
  return {
    read(entryPath) {
      const entry = entries.get(entryPath);
      if (!entry) return null;
      return buf.subarray(base + entry.offset, base + entry.offset + entry.size);
    },
    paths: [...entries.keys()],
  };
}

/** Extract the codec and its @deepseek-ai dependency closure into a cache dir. */
function extractValidator(asarPath) {
  const stat = fs.statSync(asarPath);
  const cacheDir = path.join(os.tmpdir(), 'dsh-session-validator',
    `${path.basename(asarPath)}-${stat.size}-${Math.floor(stat.mtimeMs)}`);
  const codecEntry = path.join(cacheDir, SCOPE, 'dsh-session-format-v3-to-v4/lib/index.js');
  if (!fs.existsSync(codecEntry)) {
    fs.rmSync(cacheDir, { recursive: true, force: true });
    const asar = readAsar(asarPath);
    const extracted = new Set();
    const pull = (pkg) => {
      if (extracted.has(pkg)) return;
      extracted.add(pkg);
      const prefix = `/dsh/${SCOPE}/${pkg}/`;
      for (const entryPath of asar.paths) {
        if (!entryPath.startsWith(prefix)) continue;
        if (!CODE.test(entryPath) && !entryPath.endsWith('package.json')) continue;
        const rel = entryPath.slice(prefix.length);
        const dest = path.join(cacheDir, SCOPE, pkg, rel);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, asar.read(entryPath));
      }
    };
    const pending = [...SEEDS];
    while (pending.length) {
      const pkg = pending.pop();
      pull(pkg);
      for (const file of walkFiles(path.join(cacheDir, SCOPE, pkg))) {
        if (!CODE.test(file)) continue;
        const text = fs.readFileSync(file, 'utf8');
        for (const match of text.matchAll(/from\s+"(@deepseek-ai\/[^"]+)"/g)) {
          const dep = match[1].split('/')[1];
          if (!extracted.has(dep)) pending.push(dep);
        }
      }
    }
    pull('dsh-session'); // known-event-types lives here
    fs.writeFileSync(path.join(cacheDir, 'package.json'), '{"type":"module"}');
  }
  return cacheDir;
}

function* walkFiles(dir) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walkFiles(full);
    else yield full;
  }
}

// ---------------------------------------------------------------- zstd ----
const ZSTD_MAGIC = 4247762216;

/** Split concatenated frames (mirrors DSH's scanZstdFrames). */
function splitFrames(buf) {
  const frames = [];
  let off = 0;
  while (off < buf.length) {
    const start = off;
    if (buf.length - off < 4) return { frames, torn: start };
    if (buf.readUInt32LE(off) !== ZSTD_MAGIC) throw new Error(`invalid frame magic at byte ${off}`);
    off += 4;
    if (off === buf.length) return { frames, torn: start };
    const descriptor = buf.readUInt8(off); off += 1;
    if (descriptor & 24) throw new Error(`reserved frame-header bit at byte ${off - 1}`);
    const fcsFlag = descriptor >>> 6;
    const single = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictFlag = descriptor & 3;
    off += (single ? 0 : 1) + (dictFlag === 3 ? 4 : dictFlag)
      + (fcsFlag === 0 ? (single ? 1 : 0) : 1 << fcsFlag);
    for (;;) {
      if (buf.length - off < 3) return { frames, torn: start };
      const bh = buf.readUIntLE(off, 3); off += 3;
      const last = bh & 1; const btype = (bh >>> 1) & 3; const bsize = bh >>> 3;
      if (btype === 3) throw new Error(`reserved block type at byte ${off - 3}`);
      off += btype === 1 ? 1 : bsize;
      if (last) break;
    }
    if (checksum) off += 4;
    if (off > buf.length) return { frames, torn: start };
    frames.push([start, off - start, checksum]);
  }
  return { frames, torn: undefined };
}

function decompress(file) {
  const buf = fs.readFileSync(file);
  if (!file.endsWith('.zstd')) return { text: buf.toString('utf8'), frames: null };
  const { frames, torn } = splitFrames(buf);
  if (torn !== undefined) throw new Error('incomplete final frame');
  const parts = [];
  for (const [start, length, checksum] of frames) {
    if (!checksum) throw new Error('frame without a content checksum');
    parts.push(zlib.zstdDecompressSync(buf.subarray(start, start + length)));
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames };
}

// ---------------------------------------------------------------- main ----
const args = process.argv.slice(2);
const file = args.find((a) => !a.startsWith('--'));
const asarFlag = args.indexOf('--asar');
const asarPath = asarFlag >= 0 ? args[asarFlag + 1] : DEFAULT_ASAR;
if (!file) {
  console.error('usage: node validate_session_log.mjs <session.v4.jsonl.zstd> [--asar PATH]');
  process.exit(2);
}

try {
  const { text, frames } = decompress(file);
  if (frames) {
    const first = zlib.zstdDecompressSync(fs.readFileSync(file).subarray(frames[0][0], frames[0][0] + frames[0][1])).toString('utf8');
    if (first.indexOf('\n') !== first.length - 1) {
      throw new Error('first frame is not exactly one header line');
    }
  }
  const rows = text.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
  const cacheDir = extractValidator(asarPath);
  const codec = await import(pathToFileURL(path.join(cacheDir, SCOPE,
    'dsh-session-format-v3-to-v4/lib/index.js')).href);
  const { KNOWN_SESSION_EVENT_TYPES } = await import(pathToFileURL(path.join(cacheDir, SCOPE,
    'dsh-session/lib/types/known-event-types.js')).href);
  const { type, ...header } = rows[0];
  // A seeded (forked/subagent) log inherits events up to its last inherited
  // end-seed marker; the rest belong to this session.
  let inheritedEventCount = 0;
  if (header.isSeeded === true) {
    for (const event of rows.slice(1)) {
      if (event.type === 'session/end-seed' && event.data?.inherited === true) {
        inheritedEventCount = event.seq;   // the marker's own index is the cut
      }
    }
  }
  codec.restoreReleasedV4Artifact(
    { header, inheritedEventCount, events: rows.slice(1) },
    KNOWN_SESSION_EVENT_TYPES,
  );
  console.log(`OK    ${path.basename(path.dirname(file))}/${path.basename(file)}`);
} catch (error) {
  console.log(`FAIL  ${path.basename(path.dirname(file))}/${path.basename(file)}  ->  ${error.name}: ${error.message}`);
  process.exit(1);
}