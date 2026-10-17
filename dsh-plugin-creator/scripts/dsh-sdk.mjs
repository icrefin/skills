#!/usr/bin/env node
/**
 * Read the shipped DeepSeek Harness SDK straight out of the installation.
 *
 * The desktop app ships its runtime inside an Electron `app.asar`, which only
 * Electron's patched `fs` can open: `cat`, `cp`, ripgrep, `ls` and pnpm all
 * fail on it. This script parses the archive index once and exposes the few
 * operations an author actually needs — read a package's README, grep the
 * shipped sources, list the packages, find a UI seat, or extract a package so
 * Node can import it.
 *
 * The archive is also what makes the *installed* packages the authority: they
 * ship `lib/index.js` and `README.md`, but no `.d.ts`, so the README is the
 * contract document and `lib/` is the implementation of record.
 *
 * Usage:
 *   node scripts/dsh-sdk.mjs version
 *   node scripts/dsh-sdk.mjs list [name-substring]
 *   node scripts/dsh-sdk.mjs read <package> [relative-path]     # README.md by default
 *   node scripts/dsh-sdk.mjs find <regex> [name-substring]
 *   node scripts/dsh-sdk.mjs slots [substring]
 *   node scripts/dsh-sdk.mjs extract <package...> <destination-dir>
 *
 * Environment:
 *   DSH_ASAR   archive to read (default: the macOS installation)
 */

import fs from 'node:fs'
import path from 'node:path'

/** Default archive of a macOS installation. */
const DEFAULT_ASAR = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar'

/** Archive path prefix of the packages this script exposes. */
const SDK_ROOT = 'node_modules/@deepseek-ai'

const archive = process.env.DSH_ASAR ?? DEFAULT_ASAR

/**
 * Parse the archive's directory index.
 * The layout is a pickle header whose second uint32 is the JSON directory's
 * byte length, then that JSON, then every file's bytes back to back.
 * @param file - absolute path to the archive.
 * @returns the open handle, the entries, and the byte offset files start at.
 */
function openArchive(file) {
  const fd = fs.openSync(file, 'r')
  const head = Buffer.alloc(16)
  fs.readSync(fd, head, 0, 16, 0)
  const headerSize = head.readUInt32LE(4)
  const raw = Buffer.alloc(headerSize)
  fs.readSync(fd, raw, 0, headerSize, 8)

  const start = raw.indexOf(0x7b)
  const text = raw.toString('utf8', start)
  let depth = 0
  let end = -1
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === '{') depth += 1
    else if (text[index] === '}') {
      depth -= 1
      if (depth === 0) {
        end = index + 1
        break
      }
    }
  }
  if (end < 0) throw new Error(`dsh-sdk: the directory JSON in ${file} is truncated`)

  const entries = []
  const walk = (node, prefix) => {
    for (const [name, value] of Object.entries(node.files ?? {})) {
      const entryPath = `${prefix}/${name}`
      if (value.files) walk(value, entryPath)
      else {
        const offset = Number(value.offset)
        if (Number.isFinite(offset)) entries.push({ path: entryPath, size: value.size, offset })
      }
    }
  }
  walk(JSON.parse(text.slice(0, end)), '')

  return { fd, entries, baseOffset: 8 + headerSize }
}

const { fd, entries, baseOffset } = openArchive(archive)

/** Read one entry's bytes as UTF-8. */
function readEntry(entry) {
  const buffer = Buffer.alloc(entry.size)
  fs.readSync(fd, buffer, 0, entry.size, baseOffset + entry.offset)
  return buffer.toString('utf8')
}

/** Absolute archive path of one shipped package's file. */
const packagePath = (name, relative) => `/dsh/${SDK_ROOT}/${name}/${relative}`

/** Every shipped `@deepseek-ai/*` package name, sorted. */
function packageNames() {
  const names = new Set()
  for (const entry of entries) {
    const match = entry.path.match(new RegExp(`^/dsh/${SDK_ROOT}/([^/]+)/package\\.json$`))
    if (match) names.add(match[1])
  }
  return [...names].sort()
}

/** The dsh runtime version this installation ships. */
function runtimeVersion() {
  const entry = entries.find((candidate) => candidate.path === '/dsh/node_modules/@deepseek-ai/dsh/package.json')
  if (entry === undefined) return 'unknown'
  return JSON.parse(readEntry(entry)).version
}

/** Print and exit. */
function fail(message) {
  console.error(`dsh-sdk: ${message}`)
  process.exit(1)
}

const [command, ...args] = process.argv.slice(2)

switch (command) {
  case 'version': {
    console.log(`archive: ${archive}`)
    console.log(`dsh:     ${runtimeVersion()}`)
    console.log(`packages: ${packageNames().length} @deepseek-ai/*`)
    break
  }

  case 'list': {
    const filter = args[0] ?? ''
    console.log(packageNames().filter((name) => name.includes(filter)).join('\n'))
    break
  }

  case 'read': {
    const [name, relative = 'README.md'] = args
    if (name === undefined) fail('usage: dsh-sdk.mjs read <package> [relative-path]')
    const target = packagePath(name, relative)
    const entry = entries.find((candidate) => candidate.path === target)
    if (entry === undefined) {
      fail(`no entry ${target} — check the package name with "list", or note that unpacked files live in app.asar.unpacked`)
    }
    process.stdout.write(readEntry(entry))
    break
  }

  case 'find': {
    const [pattern, filter = ''] = args
    if (pattern === undefined) fail('usage: dsh-sdk.mjs find <regex> [name-substring]')
    const regex = new RegExp(pattern, 'i')
    let hits = 0
    for (const entry of entries) {
      if (!/^\/dsh\/node_modules\/@deepseek-ai\/.*\.(md|ts|tsx|js|json|css)$/.test(entry.path)) continue
      if (!entry.path.includes(filter)) continue
      if (entry.size > 512000) continue
      const lines = readEntry(entry).split('\n')
      for (const [index, line] of lines.entries()) {
        if (!regex.test(line)) continue
        console.log(`${entry.path}:${index + 1}: ${line.trim().slice(0, 200)}`)
        hits += 1
        if (hits >= 400) {
          console.error('dsh-sdk: stopping at 400 matches — narrow the pattern')
          fs.closeSync(fd)
          process.exit(0)
        }
      }
    }
    console.error(`dsh-sdk: ${hits} matches`)
    break
  }

  case 'slots': {
    // A slot id appears in prose as `dotted.path`. The root segment is what
    // tells a UI seat apart from a data field, so filter to known roots.
    const roots = /^(main|sidebar|settings|conversation|rightbar|shell|root|workspace)\./
    const quoted = /`([a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)+)`/g
    const seats = new Map()
    for (const entry of entries) {
      const match = entry.path.match(new RegExp(`^/dsh/${SDK_ROOT}/([^/]+)/README\\.md$`))
      if (match === null || entry.size > 300000) continue
      const body = readEntry(entry)
      for (const [, id] of body.matchAll(quoted)) {
        if (!roots.test(id)) continue
        if (!seats.has(id)) seats.set(id, new Set())
        seats.get(id).add(match[1])
      }
    }
    const filter = args[0] ?? ''
    for (const [id, owners] of [...seats].sort()) {
      if (!id.includes(filter)) continue
      console.log(`${id}\t${[...owners].sort().join(',')}`)
    }
    console.error(`dsh-sdk: ${seats.size} documented seat ids`)
    break
  }

  case 'extract': {
    const destination = args.pop()
    if (destination === undefined || args.length === 0) {
      fail('usage: dsh-sdk.mjs extract <package...> <destination-dir>')
    }
    for (const name of args) {
      const prefix = `/dsh/${SDK_ROOT}/${name}/`
      let written = 0
      for (const entry of entries) {
        if (!entry.path.startsWith(prefix)) continue
        const relative = entry.path.slice(prefix.length)
        if (relative === '') continue
        const target = path.join(destination, relative)
        fs.mkdirSync(path.dirname(target), { recursive: true })
        fs.writeFileSync(target, readEntry(entry))
        written += 1
      }
      if (written === 0) fail(`no entry under ${prefix}`)
      console.log(`${name}: ${written} files -> ${destination}`)
    }
    break
  }

  default:
    console.error(
      'usage: dsh-sdk.mjs <version|list|read|find|slots|extract> ...\n' +
        '  version                       archive path, dsh version, package count\n' +
        '  list [substring]              shipped @deepseek-ai/* package names\n' +
        '  read <pkg> [path]             print one file (README.md by default)\n' +
        '  find <regex> [substring]      search shipped package sources and docs\n' +
        '  slots [substring]             UI seat ids documented in package READMEs\n' +
        '  extract <pkg...> <dir>        materialise packages on disk',
    )
    process.exit(2)
}

fs.closeSync(fd)