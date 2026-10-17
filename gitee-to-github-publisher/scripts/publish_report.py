#!/usr/bin/env python3
"""Render one self-contained HTML report for a publish run.

The report is the artefact a human actually reads: it turns the JSON that the
other scripts emit into a light-theme page with diagrams — a severity donut, a
gate timeline, a dependency-verdict bar — plus the list of things that still
need a decision.

It reads whatever exists in the staging area and says what is missing rather
than failing, so it can be run at any point in the pipeline.

Language: ``--lang en|zh|auto``. ``auto`` (the default) follows ``$REPORT_LANG``,
then ``$LC_ALL``/``$LC_MESSAGES``/``$LANG`` — a ``zh`` locale produces the Chinese
report, which this workspace asks for by default. Only the report's own chrome is
translated; the machine-readable detail (rule ids, paths, and the reasons the
scanners emit) stays as the JSON wrote it, so a Chinese report and an English one
still agree line for line on the facts.

    python3 scripts/publish_report.py ~/.dsh/publish --repo example-tool \\
        --out ~/.dsh/publish/audit/report-example-tool.html --lang zh
"""

from __future__ import annotations

import argparse
import html
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    info,
    ok,
    publish_home,
    read_json,
    step,
    warn,
)

SEVERITY_COLOURS = {
    "critical": "#b91c1c",
    "high": "#ea580c",
    "medium": "#ca8a04",
    "low": "#0ea5e9",
    "info": "#64748b",
}
VERDICT_COLOURS = {
    "ok": "#16a34a",
    "notice": "#0ea5e9",
    "review": "#ca8a04",
    "incompatible": "#b91c1c",
    "blocked": "#b91c1c",
    "missing": "#ca8a04",
    "clear": "#16a34a",
    "unknown": "#64748b",
    "pending": "#ca8a04",
}

#: Every string the report itself contributes. Detail that comes out of the JSON
#: (rule ids, masked snippets, verdict reasons) is deliberately absent: it is the
#: same text in both languages, so the two reports agree.
LABELS: dict[str, dict[str, str]] = {
    "en": {
        "lang_name": "English",
        "title": "Publish report",
        "generated": "Generated",
        "staging": "staging",
        "source": "source",
        "on_gitee": "on Gitee",
        "status_word": "Status",
        "status_clear": "Every gate passed — the repository is published and the public artifact was re-audited.",
        "status_open": "One or more gates are blocked or not yet run. Do not treat this repository as published.",
        "kpi_blocking": "blocking findings",
        "kpi_license": "outbound license",
        "kpi_deps": "dependencies",
        "kpi_checks": "verification checks",
        "kpi_gates_not_run": "gates not run",
        "no_findings": "clean",
        "findings_word": "findings",
        "h_actions": "Remaining actions",
        "h_privacy": "Privacy findings",
        "h_license": "License",
        "h_verify": "Published-tree verification",
        "th_severity": "severity",
        "th_rule": "rule",
        "th_location": "location",
        "th_matched": "matched (masked)",
        "th_instead": "use instead",
        "th_dependency": "dependency",
        "th_version": "version",
        "th_scope": "scope",
        "th_license_col": "license",
        "th_class": "class",
        "th_verdict": "verdict",
        "th_evidence": "evidence",
        "th_status": "status",
        "th_check": "check",
        "th_detail": "detail",
        "coverage": "Coverage: {files} text file(s); history mode {mode} over {commits} commit(s). "
                    "Values are masked in this report; the full reports live beside it in the staging "
                    "area and must not be committed.",
        "more": "… {count} more",
        "outbound": "Outbound",
        "detected_from": "detected from",
        "holders": "copyright holders",
        "footer": "this report is generated from the JSON in <code>audit/</code> and is intentionally "
                  "excluded from the published tree.",
        "gate_privacy": "Privacy audit",
        "gate_license": "License compliance",
        "gate_publish": "Publish",
        "gate_verify": "Published-tree verification",
        "gate_privacy_detail": "{n} finding(s); coverage: {files} file(s), history={mode}",
        "gate_privacy_missing": "not run yet — scripts/privacy_audit.py",
        "gate_license_detail": "outbound {spdx}; {n} dependency(ies)",
        "gate_license_missing": "not run yet — scripts/license_check.py",
        "gate_publish_ok": "repository created and pushed",
        "gate_publish_missing": "not verified yet — github_publish.py",
        "gate_verify_detail": "{n} check(s); default branch {branch}",
        "gate_verify_missing": "not run yet — github_publish.py verify --reaudit",
        "act_fix": "Fix <code>{rule}</code> in <code>{path}</code> — {remediation}",
        "act_dep": "Decide on <code>{name}</code> ({license}) — {reason}",
        "act_paper": "{item} — {advice}",
        "act_verify": "{item} — {detail}",
        "act_no_privacy": "Run the privacy audit (scripts/privacy_audit.py) — no gate can pass without it.",
        "act_no_license": "Run the license check (scripts/license_check.py).",
        "act_social": "Upload a 1280×640 social preview image in Settings (no stable API).",
        "act_announce": "Announce it once — see references/promotion.md for the channels that work.",
    },
    "zh": {
        "lang_name": "中文",
        "title": "发布报告",
        "generated": "生成时间",
        "staging": "暂存目录",
        "source": "来源",
        "on_gitee": "（Gitee）",
        "status_word": "状态",
        "status_clear": "全部闸门通过——仓库已发布，公开产物也已重新审计。",
        "status_open": "仍有闸门被阻断或尚未执行，请勿把该仓库视为“已发布”。",
        "kpi_blocking": "阻断级问题",
        "kpi_license": "本项目许可证",
        "kpi_deps": "依赖数量",
        "kpi_checks": "校验项",
        "kpi_gates_not_run": "未执行的闸门",
        "no_findings": "无问题",
        "findings_word": "问题数",
        "h_actions": "待办事项",
        "h_privacy": "隐私审计问题",
        "h_license": "许可证",
        "h_verify": "已发布产物校验",
        "th_severity": "级别",
        "th_rule": "规则",
        "th_location": "位置",
        "th_matched": "命中内容（已脱敏）",
        "th_instead": "建议替换为",
        "th_dependency": "依赖",
        "th_version": "版本",
        "th_scope": "范围",
        "th_license_col": "许可证",
        "th_class": "类别",
        "th_verdict": "结论",
        "th_evidence": "证据",
        "th_status": "状态",
        "th_check": "检查项",
        "th_detail": "详情",
        "coverage": "覆盖范围：{files} 个文本文件；历史模式 {mode}，共 {commits} 个提交。本报告中的敏感值"
                    "均已脱敏；完整报告位于暂存目录的 audit/ 下，切勿提交到仓库。",
        "more": "……另有 {count} 条",
        "outbound": "本项目许可证",
        "detected_from": "识别来源",
        "holders": "版权持有人",
        "footer": "本报告由 audit/ 目录下的 JSON 生成，并刻意排除在发布产物之外。",
        "gate_privacy": "隐私审计",
        "gate_license": "许可证合规",
        "gate_publish": "发布",
        "gate_verify": "已发布产物校验",
        "gate_privacy_detail": "{n} 个问题；覆盖 {files} 个文件，历史模式 {mode}",
        "gate_privacy_missing": "尚未执行——scripts/privacy_audit.py",
        "gate_license_detail": "本项目许可证 {spdx}；{n} 个依赖",
        "gate_license_missing": "尚未执行——scripts/license_check.py",
        "gate_publish_ok": "仓库已创建并推送",
        "gate_publish_missing": "尚未校验——github_publish.py",
        "gate_verify_detail": "{n} 项检查；默认分支 {branch}",
        "gate_verify_missing": "尚未执行——github_publish.py verify --reaudit",
        "act_fix": "修复 <code>{path}</code> 中的 <code>{rule}</code>——{remediation}",
        "act_dep": "决策依赖 <code>{name}</code>（{license}）——{reason}",
        "act_paper": "{item}——{advice}",
        "act_verify": "{item}——{detail}",
        "act_no_privacy": "执行隐私审计（scripts/privacy_audit.py）——没有它任何闸门都无法通过。",
        "act_no_license": "执行许可证检查（scripts/license_check.py）。",
        "act_social": "在 Settings 中上传 1280×640 的社交预览图（该接口没有稳定的公开 API）。",
        "act_announce": "发布后只做一次宣传——可用的渠道见 references/promotion.md。",
    },
}

#: The scanners write these enums in English; a Chinese report keeps the raw
#: value (so it still matches the JSON and the other scripts) and glosses it.
SEVERITY_ZH = {"critical": "致命", "high": "高", "medium": "中", "low": "低", "info": "提示"}
STATUS_ZH = {"ok": "通过", "clear": "通过", "notice": "需保留声明", "review": "待人工决策",
             "incompatible": "不兼容", "blocked": "阻断", "missing": "缺失", "unknown": "未知",
             "pending": "待完成"}


def resolve_lang(requested: str) -> str:
    """Return ``"en"`` or ``"zh"``, from the flag first and then the environment."""
    if requested in {"en", "zh"}:
        return requested
    for name in ("REPORT_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "")
        if "zh" in value.lower():
            return "zh"
        if value.startswith(("en", "C", "POSIX")):
            return "en"
    return "en"


def esc(value: object) -> str:
    """Escape a value for HTML."""
    return html.escape("" if value is None else str(value))


def enum_label(value: str, lang: str) -> str:
    """Render a status/severity enum, glossed in Chinese when that is the language."""
    if lang != "zh":
        return esc(value)
    gloss = SEVERITY_ZH.get(value) or STATUS_ZH.get(value)
    return esc(value) + (f' <span class="muted">({esc(gloss)})</span>' if gloss else "")


# --------------------------------------------------------------------------
# Diagrams (inline SVG, no external assets)
# --------------------------------------------------------------------------


def donut(counts: dict[str, int], lang: str, size: int = 168) -> str:
    """A severity donut chart with a legend."""
    label = LABELS[lang]["findings_word"]
    total = sum(counts.values())
    radius = size / 2 - 14
    circumference = 2 * 3.141592653589793 * radius
    if total == 0:
        return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
                f'aria-label="{esc(LABELS[lang]["no_findings"])}">'
                f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" stroke="#e2e8f0" '
                f'stroke-width="22"/>'
                f'<text x="{size/2}" y="{size/2 + 6}" text-anchor="middle" font-size="15" '
                f'fill="#16a34a" font-family="system-ui">{esc(LABELS[lang]["no_findings"])}</text>'
                f'</svg>')
    parts: list[str] = []
    offset = 0.0
    for severity in ("critical", "high", "medium", "low", "info"):
        value = counts.get(severity, 0)
        if not value:
            continue
        length = circumference * value / total
        parts.append(
            f'<circle cx="{size/2}" cy="{size/2}" r="{radius}" fill="none" '
            f'stroke="{SEVERITY_COLOURS[severity]}" stroke-width="22" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {size/2} {size/2})"/>'
        )
        offset += length
    legend = "".join(
        f'<li><span class="swatch" style="background:{SEVERITY_COLOURS[severity]}"></span>'
        f'{enum_label(severity, lang)} <b>{counts.get(severity, 0)}</b></li>'
        for severity in ("critical", "high", "medium", "low", "info")
        if counts.get(severity)
    )
    return (f'<div class="donut"><svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'role="img" aria-label="{esc(label)}">{"".join(parts)}'
            f'<text x="{size/2}" y="{size/2 - 2}" text-anchor="middle" font-size="26" '
            f'fill="#0f172a" font-family="system-ui" font-weight="600">{total}</text>'
            f'<text x="{size/2}" y="{size/2 + 18}" text-anchor="middle" font-size="11" '
            f'fill="#64748b" font-family="system-ui">{esc(label)}</text></svg>'
            f'<ul class="legend">{legend}</ul></div>')


def stacked_bar(counts: dict[str, int], lang: str) -> str:
    """A horizontal stacked bar for arbitrary labelled counts."""
    total = sum(counts.values()) or 1
    segments = "".join(
        f'<div class="seg" style="width:{value / total * 100:.2f}%;background:'
        f'{VERDICT_COLOURS.get(label, "#64748b")}" title="{esc(label)}: {value}">'
        f'{value if value / total > 0.08 else ""}</div>'
        for label, value in counts.items() if value
    )
    legend = "".join(
        f'<li><span class="swatch" style="background:{VERDICT_COLOURS.get(label, "#64748b")}">'
        f'</span>{enum_label(label, lang)} <b>{value}</b></li>'
        for label, value in counts.items() if value
    )
    return f'<div class="bar">{segments}</div><ul class="legend horizontal">{legend}</ul>'


def gate_timeline(gates: list[tuple[str, str, str]], lang: str) -> str:
    """A vertical gate timeline: ``(name, status, detail)``."""
    rows = []
    for name, status, detail in gates:
        colour = VERDICT_COLOURS.get(status, "#64748b")
        rows.append(
            f'<li><span class="dot" style="background:{colour}"></span>'
            f'<div><b>{esc(name)}</b> <span class="pill" style="--c:{colour}">'
            f'{enum_label(status, lang) if lang == "zh" else esc(status)}</span>'
            f'<div class="muted">{esc(detail)}</div></div></li>'
        )
    return f'<ul class="timeline">{"".join(rows)}</ul>'


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a data table."""
    head = "".join(f"<th>{esc(name)}</th>" for name in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body or "<tr><td>—</td></tr>"}</tbody></table>'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="publish_report.py",
                                     description="Render a self-contained HTML publish report.")
    parser.add_argument("staging", nargs="?", help="staging root (default: publish home)")
    parser.add_argument("--repo", required=True, help="repository name")
    parser.add_argument("--out", help="HTML output path")
    parser.add_argument("--lang", choices=("en", "zh", "auto"), default="auto",
                        help="report language; auto follows $REPORT_LANG/$LC_ALL/$LANG")
    parser.add_argument("--open", action="store_true", help="print the file:// URL for the browser")
    args = parser.parse_args(argv)

    lang = resolve_lang(args.lang)
    L = LABELS[lang]
    staging = Path(args.staging).expanduser().resolve() if args.staging else publish_home()
    if not staging.is_dir():
        warn(f"staging directory not found: {staging}")
        return EXIT_USAGE
    audit = staging / "audit"

    privacy = read_json(audit / "privacy-report.json", {}) or {}
    license_report = read_json(audit / "license-report.json", {}) or {}
    verify = read_json(audit / f"verify-{args.repo}.json", {}) or {}
    source = read_json(staging / f"{args.repo}.gitee.json", {}) or {}

    severity_counts = privacy.get("counts") or {}
    blockers = (severity_counts.get("critical", 0) or 0) + (severity_counts.get("high", 0) or 0)
    license_verdict = (license_report.get("verdict") or "unknown").lower()

    gates: list[tuple[str, str, str]] = []
    if privacy:
        gates.append((L["gate_privacy"], "blocked" if blockers else "clear",
                      L["gate_privacy_detail"].format(
                          n=sum(severity_counts.values()),
                          files=privacy.get("coverage", {}).get("files_scanned", "?"),
                          mode=privacy.get("coverage", {}).get("history_mode", "?"))))
    else:
        gates.append((L["gate_privacy"], "missing", L["gate_privacy_missing"]))
    if license_report:
        gates.append((L["gate_license"],
                      "blocked" if license_verdict == "incompatible" else license_verdict,
                      L["gate_license_detail"].format(
                          spdx=license_report.get("outbound", {}).get("spdx", "?"),
                          n=len(license_report.get("dependencies") or []))))
    else:
        gates.append((L["gate_license"], "missing", L["gate_license_missing"]))
    gates.append((L["gate_publish"], "ok" if verify else "missing",
                  L["gate_publish_ok"] if verify else L["gate_publish_missing"]))
    if verify:
        failed = [check for check in verify.get("checks", []) if check.get("status") == "blocked"]
        gates.append((L["gate_verify"], "blocked" if failed else "clear",
                      L["gate_verify_detail"].format(
                          n=len(verify.get("checks", [])),
                          branch=verify.get("default_branch", "?"))))
    else:
        gates.append((L["gate_verify"], "missing", L["gate_verify_missing"]))

    worst_gate = "clear"
    for _, status, _ in gates:
        if status in {"blocked", "incompatible"}:
            worst_gate = "blocked"
            break
        if status in {"missing", "review", "notice"} and worst_gate == "clear":
            worst_gate = "pending"

    # ---- remaining actions -------------------------------------------------
    actions: list[str] = []
    for finding in privacy.get("findings", []):
        if finding.get("severity") in {"critical", "high"}:
            location = esc(finding.get("path")) + (
                f":{finding.get('line')}" if finding.get("line") else "")
            actions.append(L["act_fix"].format(
                rule=esc(finding.get("rule")), path=location,
                remediation=esc(finding.get("remediation"))))
    for dep in license_report.get("dependencies", []):
        if dep.get("status") in {"incompatible", "review"}:
            actions.append(L["act_dep"].format(
                name=esc(dep.get("name")), license=esc(dep.get("license")),
                reason=esc(dep.get("reason"))))
    for check in license_report.get("paperwork", []):
        if check.get("status") in {"missing", "mismatch", "action", "blocked"}:
            actions.append(L["act_paper"].format(
                item=esc(check.get("item")), advice=esc(check.get("advice"))))
    for check in verify.get("checks", []):
        if check.get("status") in {"missing", "blocked"}:
            actions.append(L["act_verify"].format(
                item=esc(check.get("item")), detail=esc(check.get("detail"))))
    if not privacy:
        actions.append(L["act_no_privacy"])
    if not license_report:
        actions.append(L["act_no_license"])
    actions.append(L["act_social"])
    actions.append(L["act_announce"])

    # ---- tables ------------------------------------------------------------
    findings = sorted(privacy.get("findings", []),
                      key=lambda item: (["critical", "high", "medium", "low", "info"].index(
                          item.get("severity", "info")), item.get("path", ""), item.get("line", 0)))
    finding_rows = [
        [f'<span class="pill" style="--c:{SEVERITY_COLOURS.get(f.get("severity"), "#64748b")}">'
         f'{enum_label(str(f.get("severity")), lang)}</span>',
         f'<code>{esc(f.get("rule"))}</code>',
         f'<code>{esc(f.get("path"))}' + (f':{f.get("line")}' if f.get("line") else "") + '</code>',
         f'<code>{esc(f.get("snippet"))}</code>',
         esc(f.get("placeholder"))]
        for f in findings[:120]
    ]
    if len(findings) > 120:
        finding_rows.append([L["more"].format(count=len(findings) - 120), "", "", "", ""])

    dep_rows = [
        [f'<code>{esc(d.get("name"))}</code>', esc(d.get("version")), esc(d.get("scope")),
         esc(d.get("license")), esc(d.get("class")),
         f'<span class="pill" style="--c:{VERDICT_COLOURS.get(d.get("status"), "#64748b")}">'
         f'{enum_label(str(d.get("status")), lang)}</span>', esc(d.get("evidence"))]
        for d in license_report.get("dependencies", [])
    ]

    verify_rows = [
        [f'<span class="pill" style="--c:{VERDICT_COLOURS.get(c.get("status"), "#64748b")}">'
         f'{enum_label(str(c.get("status")), lang)}</span>', esc(c.get("item")), esc(c.get("detail"))]
        for c in verify.get("checks", [])
    ]

    outbound = license_report.get("outbound", {})
    source_name = source.get("full_name") or ""
    generated = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    coverage = L["coverage"].format(
        files=esc(privacy.get("coverage", {}).get("files_scanned", "—")),
        mode=esc(privacy.get("coverage", {}).get("history_mode", "—")),
        commits=esc(privacy.get("coverage", {}).get("history_commits", "—")))

    document = f"""<!DOCTYPE html>
<html lang="{'zh-CN' if lang == 'zh' else 'en'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(L["title"])} — {esc(args.repo)}</title>
<style>
  :root {{
    --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc; --card:#ffffff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",
    "Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:32px 24px 64px; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  h2 {{ font-size:18px; margin:34px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:18px 20px; margin-bottom:16px; box-shadow:0 1px 2px rgba(15,23,42,.04); }}
  .banner {{ border-left:6px solid {VERDICT_COLOURS.get(worst_gate, "#64748b")}; }}
  .banner.blocked {{ border-left-color:#b91c1c; }}
  .banner.pending {{ border-left-color:#ca8a04; }}
  .banner.clear {{ border-left-color:#16a34a; }}
  .grid {{ display:grid; grid-template-columns:minmax(220px,280px) 1fr; gap:20px; align-items:start; }}
  @media (max-width:760px) {{ .grid {{ grid-template-columns:1fr; }} }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:7px 9px; border-bottom:1px solid var(--line);
    vertical-align:top; }}
  th {{ background:#f1f5f9; font-weight:600; font-size:12px; color:#475569; }}
  code {{ font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; background:#f1f5f9;
    padding:1px 5px; border-radius:4px; word-break:break-all; }}
  .pill {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px;
    font-weight:600; color:#fff; background:var(--c,#64748b); }}
  .muted {{ color:var(--muted); font-size:12px; }}
  ul.legend {{ list-style:none; padding:0; margin:14px 0 0; font-size:13px; }}
  ul.legend.horizontal {{ display:flex; gap:16px; flex-wrap:wrap; }}
  ul.legend li {{ display:flex; align-items:center; gap:6px; margin-bottom:4px; }}
  .swatch {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
  .donut {{ display:flex; gap:18px; align-items:center; }}
  .donut svg {{ flex:0 0 auto; }}
  .bar {{ display:flex; height:26px; border-radius:6px; overflow:hidden; background:#e2e8f0; }}
  .bar .seg {{ color:#fff; font-size:11px; font-weight:600; display:flex; align-items:center;
    justify-content:center; }}
  ul.timeline {{ list-style:none; padding:0; margin:0; }}
  ul.timeline li {{ display:flex; gap:12px; padding:9px 0; border-bottom:1px dashed var(--line); }}
  ul.timeline li:last-child {{ border-bottom:none; }}
  .dot {{ width:11px; height:11px; border-radius:50%; margin-top:6px; flex:0 0 auto; }}
  ol.actions li {{ margin-bottom:8px; }}
  .kpi {{ display:flex; gap:26px; flex-wrap:wrap; }}
  .kpi div {{ min-width:110px; }}
  .kpi b {{ display:block; font-size:22px; }}
  footer {{ color:var(--muted); font-size:12px; margin-top:40px; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{esc(L["title"])} — {esc(args.repo)}</h1>
  <div class="sub">{esc(L["generated"])} {esc(generated)} · {esc(L["staging"])}
    <code>{esc(staging)}</code>
    {f'· {esc(L["source"])} <code>{esc(source_name)}</code> {esc(L["on_gitee"])}' if source_name else ''}</div>

  <div class="card banner {esc(worst_gate)}">
    <h2 style="margin-top:0;border:none;padding:0">{esc(L["status_word"])}: {esc(worst_gate.upper())}</h2>
    <div class="muted">{esc(L["status_clear"] if worst_gate == 'clear' else L["status_open"])}</div>
    <div class="kpi" style="margin-top:14px">
      <div><b>{blockers}</b><span class="muted">{esc(L["kpi_blocking"])}</span></div>
      <div><b>{esc(outbound.get('spdx', '—'))}</b><span class="muted">{esc(L["kpi_license"])}</span></div>
      <div><b>{len(license_report.get('dependencies') or [])}</b><span class="muted">{esc(L["kpi_deps"])}</span></div>
      <div><b>{len(verify.get('checks') or [])}</b><span class="muted">{esc(L["kpi_checks"])}</span></div>
      <div><b>{sum(1 for _, status, _ in gates if status == 'missing')}</b><span class="muted">{esc(L["kpi_gates_not_run"])}</span></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">{donut(severity_counts, lang)}</div>
    <div class="card">{gate_timeline(gates, lang)}</div>
  </div>

  <h2>{esc(L["h_actions"])}</h2>
  <div class="card"><ol class="actions">{''.join(f'<li>{item}</li>' for item in actions)}</ol></div>

  <h2>{esc(L["h_privacy"])}</h2>
  <div class="card">
    {table([L["th_severity"], L["th_rule"], L["th_location"], L["th_matched"], L["th_instead"]], finding_rows)}
    <p class="muted" style="margin-top:12px">{coverage}</p>
  </div>

  <h2>{esc(L["h_license"])}</h2>
  <div class="card">
    <p>{esc(L["outbound"])}: <b>{esc(outbound.get('spdx', 'unknown'))}</b>
      {('· ' + esc(L["detected_from"]) + ' ' + esc(', '.join(outbound.get('files') or []))) if outbound.get('files') else ''}
      {('· ' + esc(L["holders"]) + ': ' + esc(', '.join(outbound.get('holders') or []))) if outbound.get('holders') else ''}</p>
    {stacked_bar({label: sum(1 for d in license_report.get('dependencies', []) if d.get('status') == label)
                  for label in ('ok', 'notice', 'review', 'incompatible')}, lang)}
    <div style="margin-top:14px">{table([L["th_dependency"], L["th_version"], L["th_scope"], L["th_license_col"], L["th_class"], L["th_verdict"], L["th_evidence"]], dep_rows)}</div>
  </div>

  <h2>{esc(L["h_verify"])}</h2>
  <div class="card">{table([L["th_status"], L["th_check"], L["th_detail"]], verify_rows)}</div>

  <footer>gitee-to-github-publisher · {L["footer"]}</footer>
</div>
</body>
</html>
"""

    target = Path(args.out).expanduser() if args.out else audit / f"report-{args.repo}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    step("publish report")
    info(f"language        : {L['lang_name']}")
    info(f"privacy findings: {sum(severity_counts.values())} ({blockers} blocking)")
    info(f"license verdict : {license_verdict}")
    info(f"verification    : {len(verify.get('checks') or [])} check(s)")
    ok(f"report: {target}")
    if args.open:
        info(f"open this in the built-in browser: file://{target}")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)
