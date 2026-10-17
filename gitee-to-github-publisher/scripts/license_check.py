#!/usr/bin/env python3
"""License detection, dependency-license inventory, and an outbound=inbound verdict.

A repository's own LICENSE is only half the question. The other half is every
dependency it links, bundles or imports: a permissive project that depends on a
GPL library cannot be published under its own terms, and a repository that was
cloned from someone else cannot be relicensed at all.

This script answers three questions:

1. **What license is this repository under?**  Detected from the license file
   *and* the package manifests, with a mismatch reported rather than hidden.
2. **What licenses do its dependencies carry?**  Read from the installed trees
   (``node_modules``, a Python ``site-packages``, ``vendor``) when they exist,
   otherwise from the manifests — which is weaker evidence and says so.
3. **Do they fit together?**  A per-dependency verdict with the reason, plus the
   compliance paperwork the combination requires (NOTICE, attribution, source
   offer, contribution terms).

Usage
-----
    python3 scripts/license_check.py REPO_DIR --report audit/license-report.md \
        --json audit/license-report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    fail,
    git,
    info,
    ok,
    step,
    warn,
    write_json,
)

# --------------------------------------------------------------------------
# License identity
# --------------------------------------------------------------------------

#: Canonical SPDX id -> (class, human name). ``class`` drives the verdict.
LICENSES: dict[str, tuple[str, str]] = {
    # permissive
    "MIT": ("permissive", "MIT License"),
    "MIT-0": ("permissive", "MIT No Attribution"),
    "X11": ("permissive", "X11 License"),
    "BSD-2-Clause": ("permissive", "BSD 2-Clause"),
    "BSD-3-Clause": ("permissive", "BSD 3-Clause"),
    "0BSD": ("permissive", "BSD Zero Clause"),
    "ISC": ("permissive", "ISC License"),
    "Apache-2.0": ("permissive", "Apache License 2.0"),
    "Apache-1.1": ("permissive", "Apache License 1.1"),
    "Zlib": ("permissive", "zlib License"),
    "libpng-2.0": ("permissive", "libpng License"),
    "BSL-1.0": ("permissive", "Boost Software License 1.0"),
    "Python-2.0": ("permissive", "Python License 2.0"),
    "PSF-2.0": ("permissive", "Python Software Foundation License 2.0"),
    "MulanPSL-2.0": ("permissive", "Mulan Permissive Software License v2"),
    "WTFPL": ("public-domain", "Do What The Fuck You Want To Public License"),
    "Unlicense": ("public-domain", "The Unlicense"),
    "CC0-1.0": ("public-domain", "Creative Commons Zero v1.0 Universal"),
    "CC-BY-4.0": ("permissive", "Creative Commons Attribution 4.0"),
    "CC-BY-SA-4.0": ("weak-copyleft", "Creative Commons Attribution-ShareAlike 4.0"),
    "OFL-1.1": ("permissive", "SIL Open Font License 1.1"),
    # weak / file-level copyleft
    "LGPL-2.1": ("weak-copyleft", "GNU Lesser General Public License v2.1"),
    "LGPL-2.1-only": ("weak-copyleft", "GNU LGPL v2.1 only"),
    "LGPL-2.1-or-later": ("weak-copyleft", "GNU LGPL v2.1 or later"),
    "LGPL-3.0": ("weak-copyleft", "GNU Lesser General Public License v3.0"),
    "LGPL-3.0-only": ("weak-copyleft", "GNU LGPL v3.0 only"),
    "LGPL-3.0-or-later": ("weak-copyleft", "GNU LGPL v3.0 or later"),
    "MPL-2.0": ("weak-copyleft", "Mozilla Public License 2.0"),
    "EPL-1.0": ("weak-copyleft", "Eclipse Public License 1.0"),
    "EPL-2.0": ("weak-copyleft", "Eclipse Public License 2.0"),
    "CDDL-1.0": ("weak-copyleft", "Common Development and Distribution License"),
    "CDDL-1.1": ("weak-copyleft", "Common Development and Distribution License 1.1"),
    # strong copyleft
    "GPL-2.0": ("strong-copyleft", "GNU General Public License v2.0"),
    "GPL-2.0-only": ("strong-copyleft", "GNU GPL v2.0 only"),
    "GPL-2.0-or-later": ("strong-copyleft", "GNU GPL v2.0 or later"),
    "GPL-3.0": ("strong-copyleft", "GNU General Public License v3.0"),
    "GPL-3.0-only": ("strong-copyleft", "GNU GPL v3.0 only"),
    "GPL-3.0-or-later": ("strong-copyleft", "GNU GPL v3.0 or later"),
    "EUPL-1.2": ("strong-copyleft", "European Union Public License 1.2"),
    "CECILL-2.1": ("strong-copyleft", "CeCILL 2.1"),
    # network copyleft / source-available
    "AGPL-3.0": ("network-copyleft", "GNU Affero General Public License v3.0"),
    "AGPL-3.0-only": ("network-copyleft", "GNU AGPL v3.0 only"),
    "AGPL-3.0-or-later": ("network-copyleft", "GNU AGPL v3.0 or later"),
    "SSPL-1.0": ("source-available", "Server Side Public License"),
    "BUSL-1.1": ("source-available", "Business Source License 1.1"),
    "Elastic-2.0": ("source-available", "Elastic License 2.0"),
    "Commons-Clause": ("source-available", "Commons Clause"),
    "Proprietary": ("proprietary", "Proprietary / all rights reserved"),
    "UNKNOWN": ("unknown", "Unknown or absent license"),
}

#: Class -> how it behaves once someone else's code depends on it.
CLASS_NOTE = {
    "permissive": "Permissive: keep the copyright notice and license text.",
    "public-domain": "Public domain dedication: no conditions in practice.",
    "weak-copyleft": "File/library-level copyleft: you may combine, but modifications to the "
                     "covered files must stay under the same license, and notices must be kept.",
    "strong-copyleft": "Strong copyleft: the combined work must be distributed under GPL terms.",
    "network-copyleft": "Network copyleft: even offering the software over a network triggers the "
                        "source-availability obligation.",
    "source-available": "Not open source. Redistribution and commercial use are restricted.",
    "proprietary": "All rights reserved: no redistribution right is granted to you.",
    "unknown": "No license granted: the default is all rights reserved.",
}

#: Fingerprints for identifying a license file: (spdx, required phrases).
FINGERPRINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGPL-3.0", ("gnu affero general public license", "version 3")),
    ("GPL-3.0", ("gnu general public license", "version 3", "29 june 2007")),
    ("GPL-2.0", ("gnu general public license", "version 2", "june 1991")),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3")),
    ("LGPL-2.1", ("gnu lesser general public license", "version 2.1")),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license version 2.0",)),
    ("MIT", ("permission is hereby granted, free of charge", "without restriction")),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software",)),
    ("BSD-3-Clause", ("redistributions of source code must retain", "neither the name of")),
    ("BSD-2-Clause", ("redistributions of source code must retain", "redistributions in binary form")),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
    ("CC0-1.0", ("creative commons legal code", "cc0 1.0 universal")),
    ("WTFPL", ("do what the fuck you want to public license",)),
    ("BSL-1.0", ("boost software license", "version 1.0")),
    ("Zlib", ("this software is provided 'as-is'", "altered source versions must be plainly marked")),
    ("EPL-2.0", ("eclipse public license - v 2.0",)),
    ("MulanPSL-2.0", ("mulan permissive software license", "version 2")),
    ("EUPL-1.2", ("european union public licence", "v. 1.2")),
    ("CC-BY-SA-4.0", ("attribution-sharealike 4.0 international",)),
    ("CC-BY-4.0", ("attribution 4.0 international",)),
    ("SSPL-1.0", ("server side public license",)),
    ("BUSL-1.1", ("business source license 1.1",)),
    ("Elastic-2.0", ("elastic license 2.0",)),
)

LICENSE_FILE_NAMES = (
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "LICENCE.txt",
    "COPYING", "COPYING.md", "COPYING.txt", "LICENSE-MIT", "LICENSE-APACHE",
    "LICENSE.rst", "UNLICENSE", "NOTICE", "NOTICE.md", "NOTICE.txt",
)
LICENSE_BASENAMES = {"license", "licence", "copying", "unlicense", "copyright"}

SPDX_DECLARED = re.compile(r"(?i)SPDX-License-Identifier:\s*([A-Za-z0-9.\-+ ()]+)")

# --------------------------------------------------------------------------
# License expression normalisation
# --------------------------------------------------------------------------

_ALIASES = {
    "mit license": "MIT",
    "the mit license": "MIT",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "bsd": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause",
    "bsd-3": "BSD-3-Clause",
    "bsd license": "UNKNOWN",
    "gpl": "UNKNOWN",
    "gplv2": "GPL-2.0",
    "gplv3": "GPL-3.0",
    "gpl-2": "GPL-2.0",
    "gpl-3": "GPL-3.0",
    "lgplv3": "LGPL-3.0",
    "isc license": "ISC",
    "mpl 2.0": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "mulanpsl2": "MulanPSL-2.0",
    "mulanpsl-2.0": "MulanPSL-2.0",
    "mulan psl v2": "MulanPSL-2.0",
    "psf": "PSF-2.0",
    "python software foundation license": "PSF-2.0",
    "public domain": "Unlicense",
    "proprietary": "Proprietary",
    "commercial": "Proprietary",
    "none": "Proprietary",
    "": "UNKNOWN",
}


def normalise(raw: str | None) -> str:
    """Map a manifest's license string to an SPDX id we know something about."""
    if not raw:
        return "UNKNOWN"
    text = str(raw).strip().strip("()")
    # A composite expression: judge by its most restrictive member.
    if re.search(r"\bOR\b", text, re.I):
        return "UNKNOWN"  # dual licensing needs a human decision
    if re.search(r"\bAND\b|[,/]", text):
        parts = [part.strip() for part in re.split(r"\bAND\b|[,/]", text, flags=re.I) if part.strip()]
        if parts:
            return most_restrictive([normalise(single) for single in parts])
    if text in LICENSES:
        return text
    lowered = text.lower().replace(" license", "").strip()
    for alias, spdx in _ALIASES.items():
        if lowered == alias:
            return spdx
    for spdx in sorted(LICENSES, key=len, reverse=True):
        if spdx.lower() == lowered or spdx.lower().rstrip("-only").rstrip("-or-later") == lowered:
            return spdx
    if "see license in" in lowered or lowered in {"unlicensed", "unknown"}:
        return "UNKNOWN"
    if "mulan" in lowered:
        return "MulanPSL-2.0"
    if "agpl" in lowered:
        return "AGPL-3.0"
    if "lgpl" in lowered:
        return "LGPL-3.0"
    if "gpl" in lowered:
        return "GPL-3.0" if "3" in lowered else "GPL-2.0"
    if "apache" in lowered:
        return "Apache-2.0"
    if "mit" in lowered:
        return "MIT"
    if "bsd" in lowered:
        return "BSD-3-Clause"
    if "mozilla" in lowered or "mpl" in lowered:
        return "MPL-2.0"
    return "UNKNOWN"


_RESTRICTIVENESS = {
    "public-domain": 0,
    "permissive": 1,
    "unknown": 2,
    "weak-copyleft": 3,
    "strong-copyleft": 4,
    "network-copyleft": 5,
    "source-available": 6,
    "proprietary": 7,
}


def most_restrictive(spdx_ids: list[str]) -> str:
    """Return the id in ``spdx_ids`` that imposes the most obligations."""
    if not spdx_ids:
        return "UNKNOWN"
    return max(spdx_ids, key=lambda spdx: _RESTRICTIVENESS[LICENSES.get(spdx, LICENSES["UNKNOWN"])[0]])


def license_class(spdx: str) -> str:
    """Return the behavioural class of an SPDX id."""
    return LICENSES.get(spdx, LICENSES["UNKNOWN"])[0]


def license_name(spdx: str) -> str:
    """Return a human-readable name for an SPDX id."""
    return LICENSES.get(spdx, LICENSES["UNKNOWN"])[1]


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------

#: Statuses, worst last, so a repo verdict is the max over dependencies.
STATUS_ORDER = {"ok": 0, "notice": 1, "review": 2, "incompatible": 3}


def verdict_for(repo_spdx: str, dep_spdx: str) -> tuple[str, str]:
    """Return ``(status, reason)`` for one dependency under one project license."""
    repo = license_class(repo_spdx)
    dep = license_class(dep_spdx)

    if dep in {"proprietary", "unknown"}:
        return ("review", f"'{dep_spdx}' grants no clear rights: confirm you may redistribute it, "
                          f"or replace the dependency.")
    if dep == "source-available":
        return ("incompatible", f"'{dep_spdx}' is source-available, not open source; it usually "
                                f"forbids the use you want.")
    if repo in {"proprietary", "unknown"}:
        return ("review", "This project has no detected outbound license, so no dependency can be "
                          "cleared. Choose one first (see --suggest).")

    strong = {"strong-copyleft", "network-copyleft"}
    if repo == "permissive":
        if dep in {"permissive", "public-domain"}:
            return ("ok", CLASS_NOTE[dep])
        if dep == "weak-copyleft":
            return ("notice", "Combine only as a separate library/module (dynamic linking or an "
                              "unmodified published package); keep its notices and do not relicense "
                              "its files.")
        if dep in strong:
            return ("incompatible",
                    f"A {dep_spdx} dependency forces the whole distributed work under "
                    f"{'AGPL-3.0' if dep == 'network-copyleft' else 'GPL'}. Relicense this project, "
                    f"or replace the dependency.")
    if repo == "public-domain":
        if dep in {"permissive", "public-domain"}:
            return ("ok", CLASS_NOTE[dep])
        return ("notice", "A public-domain project can consume anything, but the dependency's own "
                          "terms still travel with it — keep the notices.")
    if repo == "weak-copyleft":
        if dep in {"permissive", "public-domain", "weak-copyleft"}:
            return ("notice", "Same-family or permissive dependency: eligible for the license's "
                              "secondary-license upgrade path; keep every notice.")
        if dep in strong:
            if dep_spdx.startswith("GPL-3") and repo_spdx.startswith(("LGPL-3", "MPL-2.0")):
                return ("notice", f"'{repo_spdx}' may be upgraded to '{dep_spdx}' when combined; "
                                  f"record that choice in the README.")
            return ("incompatible", f"'{dep_spdx}' cannot be combined with '{repo_spdx}' "
                                    f"without relicensing.")
    if repo in strong or repo == "network-copyleft":
        gpl3_family = repo in {"network-copyleft"} or repo_spdx.startswith("GPL-3")
        if dep_spdx == "Apache-2.0" and not gpl3_family:
            return ("incompatible", "Apache-2.0 is incompatible with GPL-2.0-only (patent and "
                                    "additional-restriction clauses). Use GPL-3.0 or drop the "
                                    "dependency.")
        if dep_spdx in {"GPL-2.0", "GPL-2.0-only"} and gpl3_family:
            return ("incompatible", "GPL-2.0-only code cannot be combined with GPL-3.0/AGPL-3.0.")
        if dep in {"permissive", "public-domain"}:
            return ("notice", f"'{dep_spdx}' code is redistributed inside a "
                              f"'{repo_spdx}' work: keep its notices, and note that you may not add "
                              f"restrictions on top.")
        if dep == "weak-copyleft":
            return ("notice", "Keep the library's notices and any modification notices.")
        return ("notice", "Same copyleft family: the combined work stays under this license.")
    return ("review", "Unhandled combination — decide with a human.")


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


@dataclass
class Detection:
    """The outbound license picture."""

    spdx: str = "UNKNOWN"
    source: str = ""
    files: list[str] = field(default_factory=list)
    declared: list[tuple[str, str]] = field(default_factory=list)  # (manifest, spdx)
    holders: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


def detect_license_files(repo: Path) -> tuple[str, list[str], list[str]]:
    """Return ``(spdx, files, copyright_holders)`` for the repository's license files."""
    files: list[str] = []
    holders: list[str] = []
    best = "UNKNOWN"
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or any(part in {".git", "node_modules", ".venv", "venv", "dist", "build"}
                                     for part in path.parts):
            continue
        name = path.name
        if name not in LICENSE_FILE_NAMES and name.split(".")[0].lower() not in LICENSE_BASENAMES:
            continue
        if path.stat().st_size > 400_000:
            continue
        rel = str(path.relative_to(repo))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append(rel)
        for match in re.finditer(r"(?i)copyright\s*(?:\(c\)|©)?\s*\d{4}(?:[-,]\s*\d{4})*\s+([^\n,;<]{2,60})",
                                 text):
            holder = match.group(1).strip()
            if holder and holder not in holders:
                holders.append(holder)
        lowered = " ".join(text.lower().split())
        for spdx, phrases in FINGERPRINTS:
            if all(phrase.lower() in lowered for phrase in phrases):
                if best == "UNKNOWN" or _RESTRICTIVENESS[license_class(spdx)] < _RESTRICTIVENESS[license_class(best)]:
                    best = spdx
                break
    return best, files, holders


MANIFESTS = (
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml",
    "composer.json", "pom.xml", "Gemfile", "go.mod", "DESCRIPTION", "*.gemspec",
)


def detect_declared(repo: Path) -> list[tuple[str, str]]:
    """Read the license a manifest *claims* (may disagree with the file)."""
    declared: list[tuple[str, str]] = []

    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            document = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = {}
        if isinstance(document, dict):
            declared.append(("package.json", normalise(document.get("license") or document.get("licenses"))))

    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        found = re.search(r"(?m)^\s*license\s*=\s*(?:\{\s*text\s*=\s*)?[\"']([^\"']+)[\"']", text)
        if not found:
            found = re.search(r"(?m)^\s*license\s*=\s*\{[^}]*file\s*=\s*[\"']([^\"']+)[\"']", text)
        classifiers = re.findall(r"License\s*::\s*([^\"'\n]+)", text)
        if found:
            declared.append(("pyproject.toml", normalise(found.group(1))))
        elif classifiers:
            declared.append(("pyproject.toml", normalise(classifiers[-1])))

    for name in ("setup.py", "setup.cfg"):
        candidate = repo / name
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            found = re.search(r"license\s*[=:]\s*[\"']([^\"']+)[\"']", text)
            if found:
                declared.append((name, normalise(found.group(1))))

    cargo = repo / "Cargo.toml"
    if cargo.is_file():
        text = cargo.read_text(encoding="utf-8", errors="replace")
        found = re.search(r"(?m)^\s*license\s*=\s*[\"']([^\"']+)[\"']", text)
        if found:
            declared.append(("Cargo.toml", normalise(found.group(1))))

    composer = repo / "composer.json"
    if composer.is_file():
        try:
            document = json.loads(composer.read_text(encoding="utf-8"))
            declared.append(("composer.json", normalise(document.get("license"))))
        except (OSError, json.JSONDecodeError):
            pass

    return declared


@dataclass
class Dependency:
    """One dependency and the evidence behind its license."""

    name: str
    version: str
    license: str
    ecosystem: str
    scope: str  # runtime | dev | build
    evidence: str  # installed | manifest


# --------------------------------------------------------------------------
# Dependency inventories
# --------------------------------------------------------------------------


def node_dependencies(repo: Path) -> list[Dependency]:
    """Read Node dependencies; prefer the installed tree over the manifest."""
    deps: list[Dependency] = []
    package_json = repo / "package.json"
    if not package_json.is_file():
        return deps
    try:
        document = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deps
    for section, scope in (("dependencies", "runtime"), ("optionalDependencies", "runtime"),
                           ("peerDependencies", "runtime"), ("devDependencies", "dev")):
        for name, requirement in (document.get(section) or {}).items():
            installed = repo / "node_modules" / name / "package.json"
            if installed.is_file():
                try:
                    meta = json.loads(installed.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
                raw = meta.get("license") or meta.get("licenses")
                if isinstance(raw, list):
                    raw = " AND ".join(str(item.get("type", item)) if isinstance(item, dict) else str(item)
                                       for item in raw)
                if isinstance(raw, dict):
                    raw = raw.get("type")
                deps.append(Dependency(name, str(meta.get("version", requirement)), normalise(raw),
                                       "node", scope, "installed"))
            else:
                deps.append(Dependency(name, str(requirement), "UNKNOWN", "node", scope, "manifest"))
    return deps


def python_dependencies(repo: Path) -> list[Dependency]:
    """Read Python dependencies; use installed dist-info metadata when available."""
    deps: list[Dependency] = []
    names: dict[str, str] = {}
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", text)
        if block:
            for entry in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
                names[re.split(r"[<>=!~\[; ]", entry.strip())[0].lower()] = entry.strip()
        for section in re.findall(r"(?ms)^\[(?:project\.optional-dependencies|dependency-groups|\w+\.dev)\]"
                                  r"(.*?)(?=^\[|\Z)", text):
            for entry in re.findall(r"[\"']([^\"']+)[\"']", section):
                if not entry.startswith(("http", "git+")):
                    names.setdefault(re.split(r"[<>=!~\[; ]", entry.strip())[0].lower(), entry.strip())
    for requirements in sorted(repo.glob("requirements*.txt")):
        for line in requirements.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            names.setdefault(re.split(r"[<>=!~\[; ]", line)[0].lower(), line)
    for name, requirement in names.items():
        deps.append(Dependency(name, requirement, "UNKNOWN", "python", "runtime", "manifest"))

    # Upgrade evidence from any installed environment we can find.
    metadata: dict[str, str] = {}
    for base in list(repo.glob(".venv/lib/*/site-packages")) + list(repo.glob("venv/lib/*/site-packages")) \
            + list(repo.glob("*/site-packages")):
        for dist in base.glob("*.dist-info"):
            meta_file = dist / "METADATA"
            if not meta_file.is_file():
                continue
            header = meta_file.read_text(encoding="utf-8", errors="replace")[:4000]
            name_match = re.search(r"(?m)^Name:\s*(.+)$", header)
            license_match = re.search(r"(?m)^License:\s*(.+)$", header)
            classifiers = re.findall(r"(?m)^Classifier:\s*License\s*::\s*(.+)$", header)
            if not name_match:
                continue
            raw = license_match.group(1).strip() if license_match else ""
            if not raw or raw.upper() in {"UNKNOWN", "NONE", ""}:
                raw = classifiers[-1] if classifiers else ""
            metadata[name_match.group(1).lower()] = normalise(raw)
    for dep in deps:
        installed = metadata.get(dep.name.lower()) or metadata.get(dep.name.lower().replace("-", "_"))
        if installed:
            dep.license = installed
            dep.evidence = "installed"
    return deps


def other_dependencies(repo: Path) -> list[Dependency]:
    """Best-effort inventory for Rust, Go, PHP and Java manifests."""
    deps: list[Dependency] = []
    cargo = repo / "Cargo.toml"
    if cargo.is_file():
        text = cargo.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"(?m)^\s*([A-Za-z0-9_-]+)\s*=\s*[\"'{]", text.split("[dependencies]", 1)[-1]):
            deps.append(Dependency(name, "*", "UNKNOWN", "rust", "runtime", "manifest"))
    gomod = repo / "go.mod"
    if gomod.is_file():
        for match in re.finditer(r"(?m)^\s*([\w./-]+)\s+v\S+", gomod.read_text(encoding="utf-8", errors="replace")):
            deps.append(Dependency(match.group(1), "*", "UNKNOWN", "go", "runtime", "manifest"))
    composer = repo / "composer.json"
    if composer.is_file():
        try:
            document = json.loads(composer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = {}
        for name in (document.get("require") or {}):
            if name != "php":
                deps.append(Dependency(name, "*", "UNKNOWN", "php", "runtime", "manifest"))
        for name in (document.get("require-dev") or {}):
            deps.append(Dependency(name, "*", "UNKNOWN", "php", "dev", "manifest"))
    return deps


# --------------------------------------------------------------------------
# Provenance and paperwork
# --------------------------------------------------------------------------


@dataclass
class Provenance:
    """Whether this repository is somebody else's work."""

    derived: bool = False
    upstream: str = ""
    evidence: list[str] = field(default_factory=list)
    foreign_holders: list[str] = field(default_factory=list)
    vendored_dirs: list[str] = field(default_factory=list)
    vendor_artifacts: list[str] = field(default_factory=list)


def inspect_provenance(repo: Path, own_holders: list[str]) -> Provenance:
    """Collect the signals that say 'this is a fork or a vendored bundle'."""
    result = Provenance()
    remotes = git(["remote", "-v"], cwd=repo, check=False).stdout.strip()
    if remotes:
        result.evidence.append(f"git remotes: {remotes.splitlines()[0]}")

    first = git(["log", "--reverse", "--format=%s", "-n", "1"], cwd=repo, check=False).stdout.strip()
    if first:
        result.evidence.append(f"first commit subject: {first}")
    if re.search(r"(?i)\b(clone|fork|copy|mirror|import)\b", first + " " + remotes):
        result.derived = True
        result.upstream = remotes.splitlines()[0].split()[-1] if remotes else ""

    for candidate in ("README.md", "README.rst", "README.txt", "README", "README.zh-CN.md"):
        path = repo / candidate
        if not path.is_file():
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        found = re.search(r"(?i)(?:fork(?:ed)?\s+(?:of|from)|clone\s+of|based\s+on|derived\s+from|"
                          r"modified\s+from|upstream)\s*:?\s*\[?([^\s\]\n]+)", head)
        if found:
            result.derived = True
            result.upstream = result.upstream or found.group(1)
            result.evidence.append(f"{candidate}: {found.group(0)[:90]}")

    # `node_modules` is deliberately absent: it is the package manager's own
    # tree, its packages are inventoried as dependencies, and calling it
    # "vendored source" fired on every JavaScript project that had been
    # installed. Real vendoring is a committed copy of someone else's code.
    for name in ("vendor", "third_party", "thirdparty", "external", "deps", "subprojects"):
        path = repo / name
        if path.is_dir():
            result.vendored_dirs.append(name)

    # Copyright holders that are not the repository's own.
    own_lower = {holder.lower() for holder in own_holders}
    holders: dict[str, int] = {}
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".c", ".h", ".cpp", ".hpp", ".py", ".js",
                                                             ".ts", ".tsx", ".v", ".sv", ".go", ".rs",
                                                             ".java", ".sh"}:
            continue
        if any(part in {".git", "node_modules", ".venv", "venv", "vendor"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:3000]
        except OSError:
            continue
        for match in re.finditer(r"(?i)copyright\s*(?:\(c\)|©)?\s*\d{4}(?:[-,]\s*\d{4})*\s+([^\n,;<*]{2,60})", text):
            holder = match.group(1).strip()
            if holder and holder.lower() not in own_lower:
                holders[holder] = holders.get(holder, 0) + 1
        if len(holders) > 40:
            break
    result.foreign_holders = [f"{holder} ({count} file(s))" for holder, count in
                              sorted(holders.items(), key=lambda item: -item[1])[:20]]

    for pattern in ("*.lic", "license.dat", "licfile*", "lmutil*", "lmgrd*", "snpslmd*", "cdslmd*",
                    "*.flexlm", "*.scl", "*flexlm*"):
        for path in repo.rglob(pattern):
            if path.is_file() and ".git" not in path.parts:
                result.vendor_artifacts.append(str(path.relative_to(repo)))
    return result


def suggest_license(repo: Path, deps: list[Dependency], detection: Detection) -> str:
    """Recommend an outbound license, driven by the dependencies first."""
    classes = {license_class(dep.license) for dep in deps if dep.scope == "runtime"}
    if "network-copyleft" in classes:
        return ("AGPL-3.0  — a runtime dependency is AGPL; publishing a service on top of it "
                "requires AGPL-compatible terms (or replacing the dependency).")
    if "strong-copyleft" in classes:
        return ("GPL-3.0-or-later  — a runtime GPL dependency forces GPL terms on the distributed "
                "work. GPL-2.0-only only if every dependency is GPL-2.0-compatible "
                "(no Apache-2.0 deps).")
    if "source-available" in classes or "proprietary" in classes:
        return ("Cannot recommend: a runtime dependency is source-available or proprietary. "
                "Replace it before open-sourcing.")
    if "weak-copyleft" in classes:
        return ("Apache-2.0 or MulanPSL-2.0  — permissive enough to sit beside an MPL/LGPL "
                "dependency used as an unmodified library; keep that library's notices.")
    if (repo / "package.json").is_file() or (repo / "Cargo.toml").is_file():
        return "MIT  — the shortest permissive default, fine for libraries and apps."
    return ("Apache-2.0  — a permissive default with an explicit patent grant, often preferred for "
            "libraries and enterprise adoption. MulanPSL-2.0 is the bilingual Chinese-origin "
            "equivalent if that matters to you.")


@dataclass
class Paperwork:
    """The files that make a repository's license claim credible."""

    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (status, item, advice)


def inspect_paperwork(repo: Path, detection: Detection, provenance: Provenance) -> Paperwork:
    """Check LICENSE, NOTICE, README license section and contribution terms."""
    result = Paperwork()
    add = result.checks.append

    add(("ok" if detection.files else "missing", "LICENSE file",
         "Add a LICENSE file at the repository root; GitHub detects the license from it."))
    if detection.files:
        add(("ok" if any(name.lower().startswith(("license", "licence", "copying"))
                         for name in detection.files) else "warn",
             "canonical license file name",
             "Name the main license file `LICENSE` so GitHub's detector recognises it."))
    if detection.mismatches:
        add(("mismatch", "manifest vs LICENSE agreement", "; ".join(detection.mismatches)))
    else:
        add(("ok", "manifest vs LICENSE agreement", "The declared license matches the license file."))

    if detection.spdx == "Apache-2.0":
        add(("ok" if (repo / "NOTICE").exists() or (repo / "NOTICE.md").exists() else "warn",
             "NOTICE file (Apache-2.0 §4d)",
             "Apache-2.0 requires shipping a NOTICE file when one exists upstream. Add one with "
             "attribution, or state that there is nothing to add."))
    if detection.spdx.startswith(("GPL", "AGPL", "LGPL")):
        add(("warn", "copyleft distribution obligations",
             "State where the corresponding source is available, and keep every copyright notice."))

    readme = None
    for candidate in ("README.md", "README.rst", "README.txt", "README"):
        if (repo / candidate).is_file():
            readme = repo / candidate
            break
    if readme is None:
        add(("missing", "README license section", "Add a README; see references/bilingual-readme.md."))
    else:
        text = readme.read_text(encoding="utf-8", errors="replace")
        has_section = bool(re.search(r"(?im)^#{1,6}\s*(license|licence|许可证|授权)", text)) or \
            bool(re.search(r"(?i)\b(MIT|Apache-2\.0|GPL|AGPL|MPL|BSD|MulanPSL|ISC)\b", text))
        add(("ok" if has_section else "missing", "README license section",
             "Add a `## License` section linking to LICENSE and naming the SPDX id."))

    contributing = repo / "CONTRIBUTING.md" if (repo / "CONTRIBUTING.md").is_file() else \
        (repo / ".github" / "CONTRIBUTING.md" if (repo / ".github" / "CONTRIBUTING.md").is_file() else None)
    if contributing is None:
        add(("missing", "contribution terms",
             "Add CONTRIBUTING.md stating the inbound=outbound rule (contributions arrive under "
             "this project's license) and whether a DCO sign-off is expected. A copy-ready template "
             "ships in assets/community/CONTRIBUTING.md."))
    else:
        text = contributing.read_text(encoding="utf-8", errors="replace")
        mentions = bool(re.search(r"(?i)\b(licen[cs]e|DCO|Developer Certificate of Origin|"
                                  r"sign-off|CLA)\b", text))
        add(("ok" if mentions else "warn", "contribution terms",
             "Name the license in CONTRIBUTING.md and state the sign-off expectation."))

    if provenance.derived:
        add(("action", "derived work attribution",
             f"This repository looks derived from {provenance.upstream or 'an upstream project'}: "
             f"keep the upstream LICENSE, add an attribution/credits section to the README, and do "
             f"not relicense upstream code."))
    if provenance.vendor_artifacts:
        add(("blocked", "vendor license artifacts present",
             "Vendor license material (" + ", ".join(provenance.vendor_artifacts[:5]) + ") is not "
             "yours to publish; remove it from the tree and from history."))
    if provenance.foreign_holders:
        add(("warn", "foreign copyright notices",
             "Third-party notices found — verify each holder permits redistribution: "
             + "; ".join(provenance.foreign_holders[:4])))
    if provenance.vendored_dirs:
        add(("warn", "vendored third-party sources",
             "Vendored trees (" + ", ".join(provenance.vendored_dirs) + ") need their own license "
             "files preserved and a third-party notices section."))
    return result


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def render_report(repo: Path, detection: Detection, deps: list[Dependency], results: list[tuple[Dependency, str, str]],
                  provenance: Provenance, paperwork: Paperwork, recommendation: str, repo_status: str) -> str:
    """Render the Markdown license report."""
    out: list[str] = []
    out.append(f"# License compliance — {repo.name}\n")
    out.append("> Keep this report outside the published tree (staging directory or a git-ignored "
               "`audit/` folder).\n")
    out.append(f"Verdict: **{repo_status.upper()}**\n")
    out.append("## Outbound license\n")
    out.append(f"- Detected: **{detection.spdx}** — {license_name(detection.spdx)}")
    out.append(f"- Evidence: {detection.source or 'no license file found'}")
    if detection.files:
        out.append(f"- License files: {', '.join('`' + name + '`' for name in detection.files)}")
    for manifest, spdx in detection.declared:
        marker = "matches" if spdx == detection.spdx else "**differs**"
        out.append(f"- `{manifest}` declares **{spdx}** ({marker})")
    if detection.holders:
        out.append(f"- Copyright holders in LICENSE: {', '.join(detection.holders)}")
    out.append("")

    if detection.spdx == "UNKNOWN":
        out.append("## Recommended license\n")
        out.append(f"{recommendation}\n")

    out.append("## Dependency inventory\n")
    if not deps:
        out.append("No dependency manifest found (or the project has none). "
                   "Vendor licence obligations must be established by hand.\n")
    else:
        out.append("| dependency | version | scope | license | class | evidence | verdict |")
        out.append("| --- | --- | --- | --- | --- | --- | --- |")
        for dep, status, _ in results:
            out.append(f"| `{dep.name}` | {dep.version} | {dep.scope} | {dep.license} | "
                       f"{license_class(dep.license)} | {dep.evidence} | {status} |")
        out.append("")
        out.append("`installed` evidence comes from the package's own metadata; `manifest` evidence "
                   "is the requirement list only, so the license is unverified and needs a lookup.\n")

    flagged = [(dep, status, reason) for dep, status, reason in results if status in {"incompatible", "review"}]
    if flagged:
        out.append("## Decisions required\n")
        for dep, status, reason in flagged:
            out.append(f"- **{dep.name}** ({status}) — {reason}")
        out.append("")

    notices = [(dep, reason) for dep, status, reason in results if status == "notice"]
    if notices:
        out.append("## Notices you must ship\n")
        for dep, reason in notices:
            out.append(f"- `{dep.name}` — {reason}")
        out.append("")

    out.append("## Paperwork\n")
    out.append("| status | item | advice |")
    out.append("| --- | --- | --- |")
    for status, item, advice in paperwork.checks:
        out.append(f"| {status} | {item} | {advice} |")
    out.append("")

    if provenance.evidence:
        out.append("## Provenance evidence\n")
        for line in provenance.evidence:
            out.append(f"- {line}")
        out.append("")
    if provenance.foreign_holders:
        out.append("Third-party copyright notices found in source headers:\n")
        for holder in provenance.foreign_holders:
            out.append(f"- {holder}")
        out.append("")

    out.append("## How this verdict was computed\n")
    out.append("Each dependency is classified (permissive / weak copyleft / strong copyleft / "
               "network copyleft / source-available / unknown) and compared with the project's own "
               "class. `ok` needs nothing; `notice` needs preserved notices and, for Apache-2.0, a "
               "NOTICE file; `review` needs a human decision; `incompatible` means relicense the "
               "project or replace the dependency. See `references/license-compliance.md` for the "
               "full matrix.")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="license_check.py",
        description="Detect the outbound license, inventory dependency licenses, and judge "
                    "compatibility before publishing.",
    )
    parser.add_argument("repo", help="repository working tree")
    parser.add_argument("--report", help="write a Markdown report here")
    parser.add_argument("--json", dest="json_path", help="write machine-readable results here")
    parser.add_argument("--no-deps", action="store_true", help="skip the dependency inventory")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        fail(f"not a directory: {repo}")
        return EXIT_USAGE

    step(f"License check — {repo}")

    spdx, files, holders = detect_license_files(repo)
    declared = detect_declared(repo)
    detection = Detection(spdx=spdx, files=files, holders=holders, declared=declared)
    detection.source = ", ".join(files) if files else ""
    for manifest, claimed in declared:
        if claimed not in {"UNKNOWN"} and claimed != spdx:
            detection.mismatches.append(f"`{manifest}` says {claimed}, the license file says {spdx}")
        elif claimed != "UNKNOWN" and spdx == "UNKNOWN":
            detection.spdx = claimed
            detection.source = f"{manifest} (no license file found)"

    deps: list[Dependency] = []
    if not args.no_deps:
        deps = [*node_dependencies(repo), *python_dependencies(repo), *other_dependencies(repo)]
    runtime = [dep for dep in deps if dep.scope == "runtime"]
    results: list[tuple[Dependency, str, str]] = []
    for dep in deps:
        status, reason = verdict_for(detection.spdx, dep.license)
        if dep.scope != "runtime" and status == "incompatible":
            status, reason = "review", ("development-only dependency: it is not redistributed, so the "
                                        "obligation is weaker — but do not ship it.")
        results.append((dep, status, reason))

    provenance = inspect_provenance(repo, holders)
    paperwork = inspect_paperwork(repo, detection, provenance)
    recommendation = suggest_license(repo, runtime, detection)

    worst = "ok"
    for _, status, _ in results:
        if STATUS_ORDER[status] > STATUS_ORDER[worst]:
            worst = status
    if any(status == "blocked" for status, _, _ in paperwork.checks):
        worst = "incompatible"
    if detection.spdx == "UNKNOWN":
        worst = max(worst, "review", key=lambda value: STATUS_ORDER[value])

    if not args.quiet:
        info(f"outbound: {detection.spdx} ({license_name(detection.spdx)})  "
             f"from {detection.source or 'nothing'}")
        for manifest, claimed in declared:
            if claimed != detection.spdx and claimed != "UNKNOWN":
                warn(f"{manifest} declares {claimed}, which differs from the detected license")
        if deps:
            info(f"dependencies: {len(deps)} ({len(runtime)} runtime)")
        for dep, status, reason in results:
            if status == "incompatible":
                print(f"  INCOMPATIBLE {dep.name:<24} {dep.license:<16} {reason}")
        for dep, status, reason in results:
            if status == "review":
                print(f"  review       {dep.name:<24} {dep.license:<16} {reason}")
        for status, item, advice in paperwork.checks:
            if status in {"missing", "mismatch", "blocked", "action"}:
                print(f"  {status:<12} {item}: {advice}")
        if detection.spdx == "UNKNOWN":
            warn(f"recommendation: {recommendation}")

    report = render_report(repo, detection, deps, results, provenance, paperwork, recommendation, worst)
    if args.report:
        target = Path(args.report).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
        info(f"report: {target}")
    if args.json_path:
        write_json(args.json_path, {
            "repo": str(repo),
            "verdict": worst,
            "outbound": {"spdx": detection.spdx, "files": detection.files, "holders": detection.holders,
                         "declared": detection.declared, "mismatches": detection.mismatches},
            "dependencies": [
                {"name": dep.name, "version": dep.version, "license": dep.license,
                 "class": license_class(dep.license), "scope": dep.scope, "evidence": dep.evidence,
                 "status": status, "reason": reason}
                for dep, status, reason in results
            ],
            "paperwork": [{"status": status, "item": item, "advice": advice}
                          for status, item, advice in paperwork.checks],
            "provenance": {"derived": provenance.derived, "upstream": provenance.upstream,
                           "evidence": provenance.evidence,
                           "foreign_holders": provenance.foreign_holders,
                           "vendor_artifacts": provenance.vendor_artifacts},
            "recommendation": recommendation if detection.spdx == "UNKNOWN" else "",
        })

    if detection.spdx == "UNKNOWN":
        fail("no outbound license detected — a repository without a license is 'all rights "
             "reserved' and is not publishable as open source")
        warn(f"recommendation: {recommendation}")
        return EXIT_BLOCKED
    if worst == "incompatible":
        fail("incompatible license combination — resolve it before publishing")
        return EXIT_BLOCKED
    if worst == "review":
        warn("license questions need a human decision before publishing")
        return EXIT_OK
    ok("license posture is consistent")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)