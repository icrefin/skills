#!/usr/bin/env node
// embed-diagram.mjs — turn a rendered Archify diagram into an embeddable
// fragment for a hand-authored show-me page.
//
// Archify's palette and diagram styling live in assets/template.html as CSS
// custom properties. The diagram SVG itself carries almost no color: it
// references var(--...) and expects a surrounding document to supply them.
// This script lifts the SVG plus the provably-relevant slice of the template
// CSS, scopes that CSS to a wrapper element so it cannot leak into the host
// page, namespaces the SVG's ids so several diagrams can share one page, and
// emits a self-contained fragment.
//
// Usage:
//   node embed-diagram.mjs <archify.html> --out <fragment.html>
//        [--scope <id>] [--theme light|dark]
//        [--preset classic|signal-flow|blueprint|editorial]
//        [--palette <palette.json>]
//
//   node embed-diagram.mjs <a.html> <b.html> ... --out-dir <dir>
//        writes shared.html (one stylesheet covering every diagram) plus
//        fig-1.html, fig-2.html, ... Include shared.html once per page.
//
// --palette accepts {"--var": "value", ...} to retarget the diagram to the
// host page's design tokens.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(__dirname, '..');

const PRESETS = ['classic', 'signal-flow', 'blueprint', 'editorial'];

function fail(message) {
  console.error(`embed-diagram: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const out = { positional: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const val = argv[i + 1];
      if (val === undefined || val.startsWith('--')) fail(`--${key} needs a value`);
      out[key] = val;
      i += 1;
    } else {
      out.positional.push(a);
    }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (!args.positional.length) {
  fail('usage: embed-diagram.mjs <archify.html> [more.html ...] --out <fragment.html> | --out-dir <dir>');
}

const theme = args.theme || 'light';
if (theme !== 'light' && theme !== 'dark') fail('--theme must be light or dark');
const preset = args.preset || 'classic';
if (!PRESETS.includes(preset)) fail(`--preset must be one of ${PRESETS.join(', ')}`);
const scope = (args.scope || 'd1').replace(/[^a-zA-Z0-9_-]/g, '');
const palette = args.palette ? JSON.parse(fs.readFileSync(args.palette, 'utf8')) : null;

const wrapperClass = 'sm-arch';
const wrapper = `.${wrapperClass}`;

// ---------------------------------------------------------------- SVG extract

function extractSvg(html) {
  const start = html.indexOf('<svg');
  if (start < 0) fail('no <svg> found in the rendered HTML');
  const re = /<svg\b|\/svg>/g;
  re.lastIndex = start;
  let depth = 0;
  let m;
  while ((m = re.exec(html))) {
    if (m[0] === '<svg') depth += 1;
    else {
      depth -= 1;
      if (depth === 0) return html.slice(start, re.lastIndex);
    }
  }
  return fail('unbalanced <svg> in the rendered HTML');
}

// ------------------------------------------------------------- CSS machinery

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

function splitTopLevel(css) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < css.length; i += 1) {
    const ch = css[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        out.push(css.slice(start, i + 1));
        start = i + 1;
      }
    }
  }
  const tail = css.slice(start).trim();
  if (tail) out.push(tail);
  return out;
}

// Split a selector list on commas that are not inside (), [] or "".
function splitSelectors(list) {
  const parts = [];
  let depth = 0;
  let quote = null;
  let start = 0;
  for (let i = 0; i < list.length; i += 1) {
    const ch = list[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === '(' || ch === '[') depth += 1;
    else if (ch === ')' || ch === ']') depth -= 1;
    else if (ch === ',' && depth === 0) {
      parts.push(list.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(list.slice(start));
  return parts.map((p) => p.trim()).filter(Boolean);
}

// Re-anchor one selector onto the wrapper element.
function scopeSelector(selector) {
  const s = selector.trim();
  if (s.startsWith(':root')) return wrapper + s.slice(':root'.length);
  if (s.startsWith('html')) return wrapper + s.slice('html'.length);
  if (/^\[data-(theme|preset|embed|motion|ambient)/.test(s)) return wrapper + s;
  return `${wrapper} ${s}`;
}

function inventory(svg) {
  const classes = new Set();
  for (const m of svg.matchAll(/class="([^"]+)"/g)) {
    for (const c of m[1].split(/\s+/)) if (c) classes.add(c);
  }
  const attrs = new Set();
  for (const m of svg.matchAll(/\s(data-[a-z-]+)=/g)) attrs.add(m[1]);
  return { classes, attrs };
}

function isRelevant(selector, inv) {
  if (/:root|\[data-theme|\[data-preset|\[data-node-ui|svg\[data-/.test(selector)) return true;
  for (const c of inv.classes) if (selector.includes(`.${c}`)) return true;
  for (const a of inv.attrs) if (selector.includes(a)) return true;
  return false;
}

// Walk top-level rules, keeping variable blocks, the SVG's own dependencies,
// at-rules, and anything whose selector touches the diagram's vocabulary.
function extractCss(styles, inv) {
  const kept = [];
  const seen = new Set();

  const push = (text) => {
    const key = text.replace(/\s+/g, ' ').trim();
    if (seen.has(key)) return;
    seen.add(key);
    kept.push(text.trim());
  };

  const walk = (rules, inAtRule) => {
    for (const rule of rules) {
      const braceAt = rule.indexOf('{');
      if (braceAt < 0) continue;
      const head = rule.slice(0, braceAt).trim();
      const at = head.match(/^@([a-z-]+)/i);

      if (at) {
        const name = at[1].toLowerCase();
        if (name === 'media' || name === 'supports' || name === 'layer') {
          const inner = rule.slice(braceAt + 1, rule.lastIndexOf('}'));
          const innerKept = [];
          for (const r of splitTopLevel(inner)) {
            const b = r.indexOf('{');
            if (b < 0) continue;
            const h = r.slice(0, b).trim();
            const a2 = h.match(/^@([a-z-]+)/i);
            if (a2) {
              if (['keyframes', 'font-face'].includes(a2[1].toLowerCase())) innerKept.push(r.trim());
              continue;
            }
            const scoped = splitSelectors(h).map(scopeSelector).join(', ');
            if (splitSelectors(h).some((s) => isRelevant(s, inv))) innerKept.push(`${scoped} ${r.slice(b)}`);
          }
          if (innerKept.length) push(`@${name} ${head.slice(at[0].length).trim()} {${innerKept.join('')}}`);
          continue;
        }
        // @font-face, @keyframes, @property and friends carry no selector to scope.
        if (['font-face', 'keyframes', 'property', 'charset', 'import'].includes(name)) {
          push(rule.trim());
          continue;
        }
        push(rule.trim());
        continue;
      }

      const parts = splitSelectors(head);
      if (!parts.some((s) => isRelevant(s, inv))) continue;
      const scoped = parts.map(scopeSelector).join(', ');
      push(`${scoped} ${rule.slice(braceAt)}`);
    }
  };

  for (const css of styles) walk(splitTopLevel(stripComments(css)), null);
  return kept.join('\n');
}

// -------------------------------------------------------------- id namespacing

function namespaceIds(svg, ns) {
  const ids = [...svg.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  let out = svg;
  for (const id of new Set(ids)) {
    const next = `${ns}-${id}`;
    out = out.split(`id="${id}"`).join(`id="${next}"`);
    out = out.split(`url(#${id})`).join(`url(#${next})`);
    out = out.split(`href="#${id}"`).join(`href="#${next}"`);
  }
  return out;
}

// ------------------------------------------------------------------- assemble

const inputs = args.positional;
if (!inputs.length) fail('usage: embed-diagram.mjs <archify.html> [more.html ...] --out <fragment.html> | --out-dir <dir>');

const template = fs.readFileSync(path.join(SKILL_ROOT, 'assets/template.html'), 'utf8');
const styles = [...template.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]);

const outDir = args['out-dir'];
const multi = inputs.length > 1 || Boolean(outDir);

const paletteCss = palette
  ? `${wrapper}{${Object.entries(palette).map(([k, v]) => `${k}:${v};`).join('')}}`
  : '';

const figureStyle = `<style>
.${wrapperClass}{display:block;margin:0}
.${wrapperClass} svg{display:block;width:100%;height:auto}
</style>`;

function prepare(input, index) {
  if (!fs.existsSync(input)) fail(`input not found: ${input}`);
  let svg = extractSvg(fs.readFileSync(input, 'utf8'));
  const sc = multi ? `d${index + 1}` : scope;
  svg = namespaceIds(svg, sc);
  svg = svg.replace(/(<svg\b[^>]*?)\sdata-reader-fit="[^"]*"/, '$1');
  return { input, svg, scope: sc };
}

const prepared = inputs.map(prepare);

// The dependency vocabulary is per diagram type: a sequence diagram needs rules
// an architecture diagram never touches. A page carrying several diagrams must
// therefore include the union of every diagram's dependencies — reusing one
// diagram's stylesheet for another leaves its canvas unstyled.
const union = { classes: new Set(), attrs: new Set() };
for (const p of prepared) {
  const inv = inventory(p.svg);
  for (const c of inv.classes) union.classes.add(c);
  for (const a of inv.attrs) union.attrs.add(a);
}
const scopedCss = extractCss(styles, union);

const sharedStyle = `<style>
/* Archify diagram styling, scoped to .${wrapperClass}. Generated by show-me-arch. */
${scopedCss}
${paletteCss}
.${wrapperClass}{display:block;margin:0}
.${wrapperClass} svg{display:block;width:100%;height:auto}
</style>`;

const figures = prepared.map(
  (p) => `<figure class="${wrapperClass}" data-theme="${theme}" data-preset="${preset}">\n${p.svg}\n</figure>`,
);

if (multi) {
  const dir = outDir || path.dirname(args.out);
  fs.mkdirSync(dir, { recursive: true });
  const sharedPath = path.join(dir, 'shared.html');
  fs.writeFileSync(sharedPath, `${sharedStyle}\n`);
  const figurePaths = figures.map((f, i) => {
    const p = path.join(dir, `fig-${i + 1}.html`);
    fs.writeFileSync(p, `${figureStyle}\n${f}\n`);
    return p;
  });
  console.log(JSON.stringify({
    ok: true, mode: 'multi', outDir: dir, diagrams: prepared.length,
    shared: sharedPath, figures: figurePaths,
    style: { bytes: scopedCss.length },
    union: { classes: union.classes.size, dataAttributes: union.attrs.size },
    theme, preset, paletteOverrides: palette ? Object.keys(palette).length : 0,
  }, null, 2));
} else {
  if (!args.out) fail('--out is required for a single diagram');
  fs.writeFileSync(args.out, `${sharedStyle}\n${figureStyle}\n${figures[0]}\n`);
  const inv = inventory(prepared[0].svg);
  console.log(JSON.stringify({
    ok: true, mode: 'single', input: inputs[0], output: args.out,
    scope: prepared[0].scope, theme, preset,
    diagram: { bytes: prepared[0].svg.length },
    style: { bytes: scopedCss.length },
    classes: inv.classes.size, dataAttributes: inv.attrs.size,
    paletteOverrides: palette ? Object.keys(palette).length : 0,
  }, null, 2));
}