# License compliance and contribution terms

The question is never just "does this repository have a LICENSE file". It is:

1. what license is this repository **outbound** under?
2. what licenses do the things it **uses** carry?
3. do those two fit together in a way you are allowed to publish?
4. does the repository say, in writing, how contributions arrive and under what
   terms?

`scripts/license_check.py` answers 1–3 mechanically and reports 4 as a paperwork
check. This document explains the reasoning, the matrix, and the cases the script
deliberately leaves to a human.

## SPDX identifiers and classes

Everything is normalised to an SPDX id and then to a behavioural class:

| Class | Meaning | Examples |
| --- | --- | --- |
| `public-domain` | No conditions in practice | Unlicense, CC0-1.0, WTFPL |
| `permissive` | Keep the notice, no other obligation | MIT, BSD-2/3-Clause, ISC, Apache-2.0, Zlib, BSL-1.0, **MulanPSL-2.0** |
| `weak-copyleft` | File/library-level reciprocity | MPL-2.0, LGPL-2.1/3.0, EPL-1.0/2.0, CDDL-1.0 |
| `strong-copyleft` | The combined work goes GPL | GPL-2.0, GPL-3.0, EUPL-1.2, CeCILL |
| `network-copyleft` | Copyleft triggers on network use | AGPL-3.0 |
| `source-available` | Not open source | BUSL-1.1, Elastic-2.0, SSPL-1.0, Commons Clause |
| `unknown` | No grant — default is all rights reserved | missing LICENSE, `SEE LICENSE IN`, bare `GPL` |

**MulanPSL-2.0** is the Chinese-origin permissive license, OSI-approved since
2020 with a bilingual Chinese/English text and an explicit patent grant; treat it
as Apache-2.0-like when combining ([background](https://cloud.baidu.com/article/4392626)).
A permissive project published from Gitee may therefore legitimately be MIT,
Apache-2.0 or MulanPSL-2.0.

## The compatibility matrix

Rows are the project's outbound license, columns the dependency's license.

| project ↓ / dependency → | public-domain | permissive | weak-copyleft | strong-copyleft | network | source-available / proprietary |
| --- | --- | --- | --- | --- | --- | --- |
| **permissive** (MIT, Apache-2.0, MulanPSL-2.0) | ok | ok | notice | **incompatible** | **incompatible** | **incompatible / review** |
| **public-domain** | ok | ok | notice | notice¹ | notice¹ | review |
| **weak-copyleft** (MPL, LGPL) | ok | notice | notice | incompatible² | incompatible | incompatible |
| **strong-copyleft** (GPL-3.0) | notice | notice | notice | notice | notice | incompatible |
| **GPL-2.0-only** | notice | notice³ | notice | notice | incompatible | incompatible |
| **network-copyleft** (AGPL-3.0) | notice | notice | notice | notice | notice | incompatible |

¹ A public-domain project can consume anything, but the dependency's terms still
travel with the binary — keep its notices.
² Exception: `LGPL-3.0` and `MPL-2.0` projects may move to GPL-3.0 under their own
upgrade clauses; record that choice explicitly in the README.
³ **Apache-2.0 is incompatible with GPL-2.0-only** (its patent and
additional-restriction clauses). GPL-3.0 accepts Apache-2.0. This is the single
most common real conflict in mixed Python projects.

`notice` means: you may combine, and you must ship the dependency's copyright and
license text, typically in a `NOTICE`/third-party notices section — and for
LGPL/MPL, modifications to *those files* stay under their license.

`incompatible` means: relicense the project, or replace the dependency. There is
no configuration flag that makes it go away.

## What "linking" means per ecosystem

The classes above are conservative because for most modern ecosystems, shipping
the dependency counts as distribution:

| Ecosystem | Reality |
| --- | --- |
| Python (pip/uv, `import`) | Bundled or installed side by side — a GPL dependency is a real obligation. |
| Node/TypeScript | `dependencies` are bundled or installed; `devDependencies` are not redistributed, so the obligation is weaker (still: do not ship them). |
| Rust / Go | Statically linked by default → a GPL dependency forces the binary under GPL. Go modules are compiled in. |
| C/C++ | Static linking = combined work; dynamic linking to LGPL is the classic "use as a library" case. |
| Verilog/SV, EDA flows | Vendor IP is not covered by any of this — see below. |
| Shell/pipelines calling an external tool | Running a GPL program as a separate process is generally not derivative. |

The script marks `dev`-scope conflicts as `review` rather than `incompatible`
because they are not redistributed — but a `devDependency` with no license still
cannot legally be vendored.

## Cloned, forked and vendored code

The user's own repositories include several clones of upstream projects. A clone
is **somebody else's copyrighted work**: you may publish it only with its original
license and notices intact, and you may not relicense it.

`inspect_provenance()` in the script collects the evidence (remote URL, first
commit subject, "clone of"/"fork from" in a README, `vendor/`/`third_party/`
directories, foreign `Copyright` headers). When `derived` is true:

1. keep the upstream `LICENSE` **verbatim** — do not replace it with your own;
2. add an **Attribution** section to both READMEs:

```markdown
## Attribution

This project is derived from [<upstream>](<url>), licensed under <SPDX>.
Upstream copyright and license text are retained in [LICENSE](LICENSE).
Modifications since the fork are licensed under the same terms.
```

3. state the modifications ("this fork adds X and removes Y");
4. if the upstream license requires it (Apache-2.0 §4b, BSD, MIT), state that
   files were changed;
5. never add a more restrictive license on top of upstream code.

For an **academic** project, add `CITATION.cff` from
`assets/community/CITATION.cff` so others can cite the source rather than the
mirror.

## Vendor and EDA material — not a license question

A repository about EDA tooling (Synopsys/Cadence/Mentor flows, IEEE 1735
encryption, FlexLM/`snpslmd` licensing) often contains artifacts that are simply
**not the author's to publish**:

- FlexLM/license files (`*.lic`, `license.dat`, `INCREMENT`/`SERVER` lines,
  `LM_LICENSE_FILE`, `SNPSLMD_LICENSE_FILE`, `HOSTID=` values);
- vendor binaries, patches against vendor binaries, or decrypted vendor source;
- keys or key material for a vendor protection scheme.

`privacy_audit.py` reports these as `critical`/`legal` and `license_check.py`
reports them as `blocked` in the paperwork section. The correct publish action is
to **remove the artifact**, describe the *workflow* in the README ("point
`SNPSLMD_LICENSE_FILE` at your own license server"), and let the reader supply
their own licensed copy. Publishing a license key or a decrypted vendor file is a
contract and copyright problem that no license combination fixes.

## Choosing a license when there is none

The script recommends one, dependency-driven:

| Situation | Recommendation |
| --- | --- |
| Only permissive/public-domain runtime dependencies | **MIT** (simplest) or **Apache-2.0** (explicit patent grant, enterprise-friendly); **MulanPSL-2.0** if a Chinese-origin bilingual license matters |
| A weak-copyleft runtime dependency used as a library | Apache-2.0 or MulanPSL-2.0, with the dependency's notices |
| A GPL runtime dependency | GPL-3.0-or-later (or GPL-2.0-only only if nothing is Apache-2.0) |
| An AGPL runtime dependency, or the project is a network service built on AGPL code | AGPL-3.0 |
| A source-available/proprietary runtime dependency | Do not open-source until it is replaced |
| A library meant to be embedded by others | Prefer MIT/Apache-2.0; never GPL if you want permissive consumers |

Then wire the paperwork, which is what actually makes the claim credible:

- `LICENSE` at the repository root with the full license text and a copyright
  line (`Copyright (c) <year> <holder>`), holders matching what you intend to
  publish;
- a `## License` section in **both** READMEs naming the SPDX id and linking to
  `LICENSE`;
- `NOTICE` when Apache-2.0 is involved and an upstream NOTICE exists;
- `CONTRIBUTING.md` stating the **inbound = outbound** rule (contributions arrive
  under the project license) and whether a DCO `Signed-off-by` is expected — a
  CLA is only needed if you intend to relicense later;
- for copyleft projects, a line saying where the corresponding source lives.

## Contribution terms in one paragraph (copy into CONTRIBUTING.md)

> By submitting a pull request you agree that your contribution is licensed under
> the same license as this project (`{{LICENSE}}`), and that you have the right to
> submit it. Please sign off your commits (`git commit -s`) to certify the
> [Developer Certificate of Origin](https://developercertificate.org/). New
> dependencies must carry a license compatible with `{{LICENSE}}`; say so in the
> pull-request checklist.

## What the script will not decide for you

- **Dual licensing** (`MIT OR Apache-2.0`) — reported as `UNKNOWN`; a human picks.
- **A custom or "internal" license file** — read it; some are permissive with a
  non-compete clause, which is not open source at all.
- **Database/content licenses** (ODbL, CC-BY-NC) — data has its own rules; a
  non-commercial data license makes the repository non-commercial.
- **Patents and trademarks** — a permissive license grants no trademark rights;
  the project name may still be someone else's mark.
- **Contributor agreements with an employer** — if the code was written at work,
  the employer may hold the rights regardless of what the license file says. Ask.