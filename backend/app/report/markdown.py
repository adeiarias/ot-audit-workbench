"""Export a Markdown con la estructura de la skill pentest-report-writing (marcadores [Evidencia N: …] intactos)."""
from ..scope import _lines
from .collect import ReportContext, finding_label
from .model import LABELS, PHASE_ORDER


def _intro_text(ctx: ReportContext, key: str, default_key: str) -> str:
    L = LABELS[ctx.data.language]
    text = getattr(ctx.data, key).strip()
    if text:
        return text
    client = L["client_part"].format(client=ctx.data.client) if ctx.data.client else ""
    return L[default_key].format(dut=ctx.data.dut_name or f"[{L['pending']}]", client=client)


def _pending(ctx: ReportContext, text: str) -> str:
    return text.strip() or f"[{LABELS[ctx.data.language]['pending']}]"


def render_markdown(ctx: ReportContext) -> str:
    d, c, L = ctx.data, ctx.campaign, LABELS[ctx.data.language]
    S = L["sections"]
    out = [f"# {L['title']}", "", f"**{L['dut']}:** {d.dut_name or '[' + L['pending'] + ']'}  ",
           f"**{L['client']}:** {d.client or '[' + L['pending'] + ']'}  ", f"**{L['test_type']}:** {L['test_types'][d.test_type]}  ",
           f"**{L['version']}:** {d.version} · **{L['date']}:** {ctx.report_date.isoformat()}  ",
           f"**{L['author']}:** {d.author or '[' + L['pending'] + ']'} · **{L['classification']}:** {d.classification}", ""]
    out += [f"## 1. {S[0]}", "", _intro_text(ctx, "introduction", "intro_default"), ""]
    out += [f"## 2. {S[1]}", "", _intro_text(ctx, "methodology", "method_default"), ""]
    out += [f"## 3. {S[2]}", "", f"{L['audit_type']}: {c.audit_type.value} · {L['period']}: {c.start_date}" + (f" – {c.end_date}" if c.end_date else ""), "", L["scope_intro"], ""]
    out += [f"- {line}" for line in _lines(c.scope)] or ["- –"]
    out += ["", f"## 4. {S[3]}", "", _pending(ctx, d.dut_description), ""]

    out += [f"## 5. {S[4]}", "", f"### {L['assets']}", ""]
    if ctx.assets:
        out += [f"| {L['col_ip']} | {L['col_host']} | {L['col_mac']} | {L['col_ports']} |", "|---|---|---|---|"]
        for a in ctx.assets:
            ports = ", ".join(f"{p['port']}/{p['proto']} {p.get('service', '')}".strip() for p in a.ports)
            out.append(f"| {a.ip} | {a.hostname} | {(a.mac + ' ' + (f'({a.vendor})' if a.vendor else '')).strip()} | {ports} |")
    else:
        out.append(L["no_assets"])
    out += ["", f"### {L['flows']}", ""]
    if ctx.flows:
        out += [f"| {L['col_src']} | {L['col_dst']} | {L['col_proto']} | {L['col_port']} | {L['col_pkts']} |", "|---|---|---|---|---|"]
        out += [f"| {f.src_ip} | {f.dst_ip} | {f.protocol} | {f.transport}/{f.port} | {f.packets} |" for f in ctx.flows]
        if ctx.flows_total > len(ctx.flows):
            out += ["", L["flows_more"].format(n=len(ctx.flows), total=ctx.flows_total)]
    else:
        out.append(L["no_flows"])
    if ctx.captures:
        out += ["", f"### {L['captures']}", ""] + [f"- {cap.filename} (sha256 `{cap.sha256[:16]}…`, {cap.packets} pkts)" for cap in ctx.captures]

    out += ["", f"## 6. {S[5]}", "", _pending(ctx, d.exploitation_summary), "", f"## 7. {S[6]}", "", _pending(ctx, d.remediation_summary), "", f"## 8. {S[7]}", ""]
    if not ctx.findings:
        out.append(L["no_findings"])
    n = 0
    for phase in PHASE_ORDER:
        group = [v for v in ctx.findings if v.f.phase.value == phase]
        if not group:
            continue
        n += 1
        out += [f"### 8.{n} {L['phases'][phase]}", ""]
        for v in group:
            f = v.f
            crit = f"{v.rating} ({f.cvss_score:g})" + (f": {f.cvss_vector}" if f.cvss_vector else "") if f.cvss_score is not None else f"[{L['pending']}]"
            out += [f"#### {finding_label(f)} {f.name}", "", f"**{L['f_id']}:** {finding_label(f)}  ", f"**{L['f_name']}:** {f.name}  ", f"**{L['f_crit']}:** {crit}  ",
                    f"**{L['f_assets']}:** {', '.join(v.assets) or '–'}  "]
            if v.depends_label:
                out.append(f"**{L['f_dep']}:** {v.depends_label}  ")
            out += ["", f"**{L['f_desc']}**", "", f.description.strip() or f"[{L['pending']}]", "", f"**{L['f_poc']}**", "", f.poc.strip() or f"[{L['pending']}]", "",
                    f"**{L['f_impact']}**", "", f.impact.strip() or f"[{L['pending']}]", "", f"**{L['f_rec']}**", "", f.recommendations.strip() or f"[{L['pending']}]", ""]
    out += [f"## 9. {S[8]}", "", _pending(ctx, d.conclusions), ""]
    return "\n".join(out)
