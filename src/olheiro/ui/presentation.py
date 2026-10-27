"""Identidade visual da AnalisIA. HTML decorativo; ações usam widgets nativos acessíveis."""

from html import escape

import streamlit as st

MARK = """<rect width="42" height="42" rx="12" fill="#6558E8"/>
<path d="M11 30 20 12h3l9 18h-6l-1.6-4h-7.8L15 30zm8-8h4l-2-5z" fill="white"/>
<circle cx="33" cy="10" r="4" fill="#9AE8D2"/>"""
ICON = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 42 42">{MARK}</svg>'
LOGO = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 230 52">
<g transform="translate(2 5)">{MARK}</g>
<text x="58" y="36" font-family="Arial,sans-serif" font-size="30" font-weight="700"
fill="#F5F7FF">Analis<tspan fill="#9AE8D2">IA</tspan></text></svg>"""

STYLES = """<style>
/* Seletores próprios preservam controles, foco e navegação nativos do Streamlit. */
.ai-eyebrow {font-size:.7rem;font-weight:750;letter-spacing:.16em;
    text-transform:uppercase;color:#6558E8;margin:0 0 .6rem}
.ai-context {display:flex;flex-wrap:wrap;gap:.65rem 1.2rem;align-items:center;
    padding:.85rem 1.1rem;border:1px solid #E2E6F0;border-radius:14px;
    background:#FFFFFF;color:#526079;font-size:.83rem;margin:.3rem 0 .6rem}
.ai-context strong {color:#18243B;font-weight:650}
.ai-dot {display:inline-block;width:7px;height:7px;border-radius:50%;background:#148B78;
    margin-right:.4rem}
.ai-hero {position:relative;overflow:hidden;border:1px solid #E0DDF7;border-radius:22px;
    padding:1.3rem 1.6rem;background:linear-gradient(115deg,#F0EEFF 0%,#F8FAFF 65%,#E9F7F2);
    color:#18243B;margin:.2rem 0 .5rem}
.ai-hero p {max-width:43rem;font-size:.98rem;line-height:1.7;margin:.4rem 0}
.ai-steps {display:flex;flex-wrap:wrap;gap:.6rem 1.7rem;margin-top:1.2rem;
    color:#526079;font-size:.78rem}
.ai-steps b {color:#6558E8;margin-right:.4rem}
.ai-label {font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;
    color:#5D6980;font-weight:700;margin-bottom:.6rem}
.ai-card-icon {display:inline-grid;place-items:center;width:32px;height:32px;
    background:#EEEBFF;color:#6558E8;border-radius:10px;font-size:1.15rem;margin-bottom:.4rem}
.ai-card-title {font-size:1rem;font-weight:700;margin:0 0 .3rem;color:inherit}
.ai-card-copy {font-size:.84rem;line-height:1.4;color:inherit;opacity:.78;
    min-height:2rem;margin:.3rem 0 .55rem}
.ai-empty {text-align:center;border:1px dashed #CDD4E4;border-radius:20px;padding:2.5rem 1rem;
    background:#FFFFFF;color:#526079;margin:1rem 0}
.ai-empty h3 {color:#18243B;font-size:1.2rem;margin:.8rem 0 .5rem}
.ai-empty p {max-width:32rem;line-height:1.6;margin:auto;font-size:.9rem}
.ai-summary {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.8rem;margin:0 0 1.3rem}
.ai-summary > div {background:#FFFFFF;border:1px solid #E2E6F0;
    border-radius:14px;padding:1rem 1.2rem}
.ai-summary span {display:block;color:#5D6980;font-size:.75rem;margin-bottom:.3rem}
.ai-summary strong {font-size:1.5rem;letter-spacing:-.04em;color:#18243B}
.ai-status {font-size:.8rem;padding:.7rem .85rem;border-radius:10px;
    background:#1D2A43;color:#D6E3F4;margin:.5rem 0}
.ai-status .ai-dot {background:#9AE8D2}
.ai-status-muted .ai-dot {background:#E9B969}
[data-testid="stMainBlockContainer"] {max-width:1240px;padding-top:2.3rem;padding-bottom:3rem}
[data-testid="stHeadingWithActionElements"] h1 {letter-spacing:-.045em;font-weight:700;
    padding-top:0;padding-bottom:.35rem}
[data-testid="stSidebarNav"] a {border-radius:10px}
[data-testid="stSidebar"] [data-testid="stLogo"] {max-height:52px}
[data-testid="stChatMessage"] {border:1px solid var(--border-color,#E2E6F0);
    border-radius:18px;padding:1.4rem}
[data-testid="stChatInput"] {border-radius:16px}
[class*="st-key-starter-"] {transition:transform .16s ease,border-color .16s ease;
    background:#FFFFFF;color:#18243B;border-radius:16px}
[class*="st-key-starter-"]:hover {transform:translateY(-3px);border-color:#B3ABF1}
.st-key-question-draft {border-left:3px solid #6558E8}
@media (max-width:700px) {
    [data-testid="stMainBlockContainer"] {padding-top:4.2rem;padding-left:1rem;padding-right:1rem}
    [data-testid="stHeadingWithActionElements"] h1 {font-size:2rem;line-height:1.2}
    .ai-hero {padding:1.1rem}
    .ai-context {gap:.55rem;font-size:.77rem}
    .ai-summary {gap:.4rem}
    .ai-summary > div {padding:.8rem}
    .ai-summary strong {font-size:1.2rem}
}
@media (prefers-reduced-motion:reduce) {
    [class*="st-key-starter-"] {transition:none}
    [class*="st-key-starter-"]:hover {transform:none}
}
</style>"""


def apply_identity() -> None:
    """Tema nativo para cores; CSS pequeno para composição e componentes decorativos."""
    st.logo(LOGO, icon_image=ICON, size="large")
    st.html(STYLES)


def page_intro(eyebrow: str, title: str, description: str) -> None:
    st.html(f'<p class="ai-eyebrow">{escape(eyebrow)}</p>')
    st.title(title)
    st.caption(description)


def context_strip(title: str, tables: int, columns: int) -> None:
    """Valores vêm do catálogo; nomes de bases são escapados antes do HTML."""
    st.html(
        '<div class="ai-context"><span><i class="ai-dot"></i>Base conectada</span>'
        f"<strong>{escape(title)}</strong><span>{tables} tabelas · {columns} colunas</span>"
        "<span>SQL + evidências</span></div>"
    )


def summary_tiles(items: list[tuple[str, int]]) -> None:
    tiles = "".join(
        f"<div><span>{escape(label)}</span><strong>{value}</strong></div>" for label, value in items
    )
    st.html(f'<div class="ai-summary">{tiles}</div>')


def empty_state(title: str, description: str) -> None:
    st.html(
        f'<div class="ai-empty"><span class="ai-card-icon" aria-hidden="true">↗</span>'
        f"<h3>{escape(title)}</h3><p>{escape(description)}</p></div>"
    )


def connection_status(label: str, *, configured: bool) -> None:
    css_class = "ai-status" if configured else "ai-status ai-status-muted"
    st.html(f'<div class="{css_class}"><i class="ai-dot"></i>{escape(label)}</div>')
