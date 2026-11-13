"""
Convert HANDOVER_GUIDE.md to PDF using ReportLab Platypus.
- Page numbers in footer
- Headings keepWithNext (title never orphaned from body)
- No blank pages
"""
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN       = colors.HexColor("#407E3C")
GREEN_LIGHT = colors.HexColor("#EAF3EA")
GREEN_DARK  = colors.HexColor("#2D5C29")
MUTED       = colors.HexColor("#6B7B6B")
TEXT        = colors.HexColor("#1A1A1A")
CODE_BG     = colors.HexColor("#F4F6F4")
CODE_TEXT   = colors.HexColor("#1A2B1A")
WARN_BG     = colors.HexColor("#FEF3C7")
WARN_TEXT   = colors.HexColor("#92400E")
NOTE_BG     = colors.HexColor("#EFF6FF")
NOTE_TEXT   = colors.HexColor("#1E40AF")
TIP_BG      = colors.HexColor("#F0FDF4")
TIP_TEXT    = colors.HexColor("#166534")
BORDER      = colors.HexColor("#DDE8DD")

W, H = A4
MARGIN = 20 * mm

# ── Styles ────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def S(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)

styles = {
    # Title page
    "cover_title": S("cover_title", fontSize=34, fontName="Helvetica-Bold",
                     textColor=GREEN_DARK, alignment=TA_CENTER, spaceAfter=6,
                     leading=40),
    "cover_sub":   S("cover_sub", fontSize=14, fontName="Helvetica",
                     textColor=MUTED, alignment=TA_CENTER, spaceAfter=4),
    "cover_ver":   S("cover_ver", fontSize=10, fontName="Helvetica",
                     textColor=MUTED, alignment=TA_CENTER),
    "cover_client": S("cover_client", fontSize=14, fontName="Helvetica-Bold",
                      textColor=GREEN_DARK, alignment=TA_CENTER, spaceAfter=2),

    # Part / chapter
    "part":        S("part", fontSize=22, fontName="Helvetica-Bold",
                     textColor=GREEN_DARK, spaceBefore=6, spaceAfter=4,
                     keepWithNext=1, leading=28),
    "h1":          S("h1", fontSize=17, fontName="Helvetica-Bold",
                     textColor=GREEN_DARK, spaceBefore=14, spaceAfter=4,
                     keepWithNext=1, leading=22),
    "h2":          S("h2", fontSize=14, fontName="Helvetica-Bold",
                     textColor=GREEN, spaceBefore=10, spaceAfter=3,
                     keepWithNext=1, leading=18),
    "h3":          S("h3", fontSize=12, fontName="Helvetica-Bold",
                     textColor=TEXT, spaceBefore=8, spaceAfter=2,
                     keepWithNext=1, leading=16),
    "h4":          S("h4", fontSize=11, fontName="Helvetica-BoldOblique",
                     textColor=MUTED, spaceBefore=6, spaceAfter=2,
                     keepWithNext=1, leading=14),

    # Body
    "body":        S("body", fontSize=10, fontName="Helvetica",
                     textColor=TEXT, spaceBefore=2, spaceAfter=4,
                     leading=15),
    "body_bold":   S("body_bold", fontSize=10, fontName="Helvetica-Bold",
                     textColor=TEXT, spaceBefore=2, spaceAfter=4, leading=15),

    # Code
    "code":        S("code", fontSize=8.5, fontName="Courier",
                     textColor=CODE_TEXT, backColor=CODE_BG,
                     spaceBefore=4, spaceAfter=4, leading=13,
                     leftIndent=8, rightIndent=8,
                     borderPadding=(5, 6, 5, 6)),

    # Callouts
    "note":        S("note", fontSize=9.5, fontName="Helvetica",
                     textColor=NOTE_TEXT, backColor=NOTE_BG,
                     spaceBefore=4, spaceAfter=4, leading=14,
                     leftIndent=8, rightIndent=8,
                     borderPadding=(5, 6, 5, 6)),
    "tip":         S("tip", fontSize=9.5, fontName="Helvetica",
                     textColor=TIP_TEXT, backColor=TIP_BG,
                     spaceBefore=4, spaceAfter=4, leading=14,
                     leftIndent=8, rightIndent=8,
                     borderPadding=(5, 6, 5, 6)),
    "warn":        S("warn", fontSize=9.5, fontName="Helvetica-Bold",
                     textColor=WARN_TEXT, backColor=WARN_BG,
                     spaceBefore=4, spaceAfter=4, leading=14,
                     leftIndent=8, rightIndent=8,
                     borderPadding=(5, 6, 5, 6)),

    # List items — plain paragraphs with bullet prefix (avoids ListFlowable "bull" bug)
    "li":          S("li", fontSize=10, fontName="Helvetica",
                     textColor=TEXT, spaceBefore=1, spaceAfter=1,
                     leading=14, leftIndent=18, firstLineIndent=-10),
    "li_ordered":  S("li_ordered", fontSize=10, fontName="Helvetica",
                     textColor=TEXT, spaceBefore=1, spaceAfter=1,
                     leading=14, leftIndent=22, firstLineIndent=-14),

    # Table header
    "th":          S("th", fontSize=9, fontName="Helvetica-Bold",
                     textColor=colors.white, alignment=TA_CENTER, leading=12),
    "td":          S("td", fontSize=9, fontName="Helvetica",
                     textColor=TEXT, alignment=TA_LEFT, leading=12),

    # Footer
    "footer":      S("footer", fontSize=8, fontName="Helvetica",
                     textColor=MUTED, alignment=TA_CENTER),
    "toc_entry":   S("toc_entry", fontSize=10, fontName="Helvetica",
                     textColor=TEXT, leading=16, leftIndent=0),
    "toc_ch":      S("toc_ch", fontSize=10, fontName="Helvetica",
                     textColor=TEXT, leading=16, leftIndent=12),
    "toc_sec":     S("toc_sec", fontSize=9.5, fontName="Helvetica",
                     textColor=MUTED, leading=15, leftIndent=24),
}

# ── Page template with footer ─────────────────────────────────────────────────
class NumberedCanvas:
    """Added to doc via onLaterPages / canvasMaker pattern."""
    pass

def make_footer(footer_title: str):
    """Factory so the same footer callback can label different documents."""
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        # Thin rule above footer text
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 15 * mm, W - MARGIN, 15 * mm)
        # Left: guide title  (6 mm below rule)
        canvas.drawString(MARGIN, 9 * mm, footer_title)
        # Right: page number
        page_text = f"Page {doc.page}"
        canvas.drawRightString(W - MARGIN, 9 * mm, page_text)
        canvas.restoreState()
    return _footer

def make_first_page(band_text: str):
    """Factory so the same cover-band callback can label different documents."""
    def _first_page(canvas, doc):
        # Cover page — no footer
        canvas.saveState()
        # Green header band
        canvas.setFillColor(GREEN_DARK)
        canvas.rect(0, H - 55 * mm, W, 55 * mm, fill=1, stroke=0)
        # Green bottom band
        canvas.setFillColor(GREEN)
        canvas.rect(0, 0, W, 18 * mm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.white)
        canvas.drawCentredString(W / 2, 7 * mm, band_text)
        canvas.restoreState()
    return _first_page

# ── Markdown → Flowable parser ────────────────────────────────────────────────

def escape_xml(text: str) -> str:
    """Escape chars that break ReportLab XML parser."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))

def inline_fmt(text: str) -> str:
    """Convert inline markdown (**bold**, `code`, *italic*, [text](url)) to ReportLab XML."""
    text = escape_xml(text)
    # Markdown links [text](url) -> just the text (no in-PDF navigation, but readable —
    # used by TECHNICAL_GUIDE.md's Table of Contents)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Bold+italic ***...***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # Bold **...**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic *...*
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Inline code `...`
    text = re.sub(r'`([^`]+)`',
                  r'<font name="Courier" size="8.5" color="#1A2B1A">\1</font>', text)
    return text


def parse_table(lines: list[str]) -> Table | None:
    """Parse a markdown table block into a ReportLab Table."""
    rows = []
    for line in lines:
        if re.match(r'^\s*\|[-: |]+\|\s*$', line):
            continue  # separator row
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)

    if not rows:
        return None

    col_count = max(len(r) for r in rows)
    # Pad short rows
    rows = [r + [''] * (col_count - len(r)) for r in rows]

    # Build paragraph cells
    para_rows = []
    for i, row in enumerate(rows):
        style = styles["th"] if i == 0 else styles["td"]
        para_rows.append([Paragraph(inline_fmt(c), style) for c in row])

    col_width = (W - 2 * MARGIN) / col_count
    tbl = Table(para_rows, colWidths=[col_width] * col_count, repeatRows=1)

    ts = TableStyle([
        ('BACKGROUND',  (0, 0), (-1, 0),  GREEN),
        ('TEXTCOLOR',   (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',    (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, 0),  9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, GREEN_LIGHT]),
        ('GRID',        (0, 0), (-1, -1), 0.4, BORDER),
        ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',  (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0),(-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',(0, 0), (-1, -1), 6),
    ])
    tbl.setStyle(ts)
    return tbl


def md_to_flowables(md_text: str) -> list:
    """Convert full markdown text to list of ReportLab flowables."""
    flowables = []
    lines = md_text.splitlines()
    i = 0
    n = len(lines)

    # Track whether we're in a code block
    in_code = False
    code_lines = []
    code_lang = ""

    # Track list state
    in_list = False
    list_items = []   # list of (text, is_ordered, number)
    _ol_counter = [0]

    def flush_list():
        nonlocal in_list, list_items
        if not list_items:
            return
        for txt, is_ordered, num in list_items:
            if is_ordered:
                prefix = f'<font color="#407E3C"><b>{num}.</b></font>&#160;&#160;'
                flowables.append(Paragraph(prefix + inline_fmt(txt), styles["li_ordered"]))
            else:
                prefix = '<font color="#407E3C"><b>&#8226;</b></font>&#160;&#160;'
                flowables.append(Paragraph(prefix + inline_fmt(txt), styles["li"]))
        list_items = []
        in_list = False
        _ol_counter[0] = 0

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        # ── Code fence ────────────────────────────────────────────────────────
        if stripped.startswith("```"):
            if not in_code:
                flush_list()
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            else:
                in_code = False
                code_text = "\n".join(code_lines)
                # Escape for XML, preserve newlines with <br/>
                safe = escape_xml(code_text)
                # Use pre-formatted style
                para = Paragraph(safe.replace("\n", "<br/>"), styles["code"])
                flowables.append(para)
                flowables.append(Spacer(1, 2 * mm))
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(raw)
            i += 1
            continue

        # ── Blank line ─────────────────────────────────────────────────────────
        if not stripped:
            flush_list()
            flowables.append(Spacer(1, 2 * mm))
            i += 1
            continue

        # ── Horizontal rule ────────────────────────────────────────────────────
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            flush_list()
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                        color=BORDER, spaceAfter=4, spaceBefore=4))
            i += 1
            continue

        # ── Page break marker ──────────────────────────────────────────────────
        if stripped.lower() in ("<!-- pagebreak -->", "\\newpage"):
            flush_list()
            flowables.append(PageBreak())
            i += 1
            continue

        # ── Headings ───────────────────────────────────────────────────────────
        hm = re.match(r'^(#{1,4})\s+(.*)', stripped)
        if hm:
            flush_list()
            level = len(hm.group(1))
            text  = inline_fmt(hm.group(2))

            # PART headings get special treatment
            if level == 1 and text.upper().startswith("PART"):
                flowables.append(PageBreak())
                flowables.append(Spacer(1, 8 * mm))
                flowables.append(Paragraph(text, styles["part"]))
                flowables.append(HRFlowable(width="100%", thickness=2,
                                            color=GREEN, spaceAfter=6))
            elif level == 1:
                # Chapter heading — ensure enough room for heading + rule + at least one body line
                flowables.append(CondPageBreak(60 * mm))
                heading = Paragraph(text, styles["h1"])
                rule    = HRFlowable(width="40%", thickness=1,
                                     color=GREEN_LIGHT, spaceAfter=3)
                from reportlab.platypus import KeepTogether
                flowables.append(KeepTogether([heading, rule]))
            elif level == 2:
                # Chapter-level headings always start on a new page;
                # other level-2 headings use a conditional break.
                raw_text = hm.group(2).strip()
                if raw_text.lower().startswith("chapter"):
                    flowables.append(PageBreak())
                    # Peek ahead to collect the next 1-2 body paragraphs so
                    # the heading is never orphaned from its opening text.
                    from reportlab.platypus import KeepTogether
                    heading_para = Paragraph(text, styles["h2"])
                    # Collect up to 3 non-blank, non-heading lines after this one
                    peek = i + 1
                    body_paras = []
                    collected = 0
                    while peek < n and collected < 3:
                        nxt = lines[peek].strip()
                        if not nxt or nxt.startswith("#") or nxt.startswith("|") \
                                or nxt.startswith("```") or nxt.startswith(">") \
                                or re.match(r'^[-*+]\s+', nxt) \
                                or re.match(r'^\d+\.\s+', nxt) \
                                or re.match(r'^[-*_]{3,}\s*$', nxt):
                            break
                        body_paras.append(Paragraph(inline_fmt(nxt), styles["body"]))
                        collected += 1
                        peek += 1
                    if body_paras:
                        flowables.append(KeepTogether([heading_para] + body_paras))
                        # Advance past the lines we peeked and consumed
                        i = peek
                    else:
                        flowables.append(heading_para)
                else:
                    flowables.append(CondPageBreak(50 * mm))
                    flowables.append(Paragraph(text, styles["h2"]))
            elif level == 3:
                from reportlab.platypus import KeepTogether
                h3_para = Paragraph(text, styles["h3"])
                peek = i + 1
                body_paras = []
                collected = 0
                while peek < n and collected < 2:
                    nxt = lines[peek].strip()
                    if (not nxt or nxt.startswith("#") or nxt.startswith("|")
                            or nxt.startswith("```") or nxt.startswith(">")
                            or re.match(r'^[-*+]\s+', nxt)
                            or re.match(r'^\d+\.\s+', nxt)
                            or re.match(r'^[-*_]{3,}\s*$', nxt)):
                        break
                    body_paras.append(Paragraph(inline_fmt(nxt), styles["body"]))
                    collected += 1
                    peek += 1
                if body_paras:
                    flowables.append(CondPageBreak(45 * mm))
                    flowables.append(KeepTogether([h3_para] + body_paras))
                    i = peek
                else:
                    flowables.append(CondPageBreak(40 * mm))
                    flowables.append(h3_para)
            else:
                from reportlab.platypus import KeepTogether
                h4_para = Paragraph(text, styles["h4"])
                peek = i + 1
                body_paras = []
                collected = 0
                while peek < n and collected < 2:
                    nxt = lines[peek].strip()
                    if (not nxt or nxt.startswith("#") or nxt.startswith("|")
                            or nxt.startswith("```") or nxt.startswith(">")
                            or re.match(r'^[-*+]\s+', nxt)
                            or re.match(r'^\d+\.\s+', nxt)
                            or re.match(r'^[-*_]{3,}\s*$', nxt)):
                        break
                    body_paras.append(Paragraph(inline_fmt(nxt), styles["body"]))
                    collected += 1
                    peek += 1
                if body_paras:
                    flowables.append(CondPageBreak(40 * mm))
                    flowables.append(KeepTogether([h4_para] + body_paras))
                    i = peek
                else:
                    flowables.append(CondPageBreak(35 * mm))
                    flowables.append(h4_para)
            i += 1
            continue

        # ── Callout boxes (> NOTE: / > TIP: / > WARNING: / > IMPORTANT:) ──────
        if stripped.startswith(">"):
            flush_list()
            content = stripped.lstrip("> ").strip()
            up = content.upper()
            if up.startswith("NOTE:") or up.startswith("NOTE "):
                label = "📝 NOTE"
                sty = styles["note"]
                body = content[5:].strip()
            elif up.startswith("TIP:") or up.startswith("TIP "):
                label = "💡 TIP"
                sty = styles["tip"]
                body = content[4:].strip()
            elif up.startswith("WARNING:") or up.startswith("WARNING "):
                label = "⚠️ WARNING"
                sty = styles["warn"]
                body = content[8:].strip()
            elif up.startswith("IMPORTANT:") or up.startswith("IMPORTANT "):
                label = "🔴 IMPORTANT"
                sty = styles["warn"]
                body = content[10:].strip()
            else:
                label = ""
                sty = styles["note"]
                body = content

            full = f"<b>{label}</b>  {inline_fmt(body)}" if label else inline_fmt(body)
            flowables.append(Paragraph(full, sty))
            i += 1
            continue

        # ── Table ──────────────────────────────────────────────────────────────
        if stripped.startswith("|"):
            flush_list()
            tbl_lines = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            tbl = parse_table(tbl_lines)
            if tbl:
                flowables.append(tbl)
                flowables.append(Spacer(1, 3 * mm))
            continue

        # ── Unordered list ─────────────────────────────────────────────────────
        if re.match(r'^[-*+]\s+', stripped):
            in_list = True
            text = re.sub(r'^[-*+]\s+', '', stripped)
            list_items.append((text, False, 0))
            i += 1
            continue

        # ── Ordered list ───────────────────────────────────────────────────────
        if re.match(r'^\d+\.\s+', stripped):
            in_list = True
            _ol_counter[0] += 1
            text = re.sub(r'^\d+\.\s+', '', stripped)
            list_items.append((text, True, _ol_counter[0]))
            i += 1
            continue

        # ── Normal paragraph ───────────────────────────────────────────────────
        flush_list()

        # A line that is entirely **bold** is a standalone paragraph — don't merge
        is_standalone = bool(re.match(r'^\*\*[^*]+\*\*$', stripped))

        para_lines = [stripped]
        if not is_standalone:
            j = i + 1
            while j < n:
                nxt = lines[j].strip()
                # Stop merging on: blank, heading, list, table, code, blockquote,
                # hr, or a line that is itself entirely **bold** (standalone label)
                if (not nxt or nxt.startswith("#") or nxt.startswith("|")
                        or nxt.startswith("```") or nxt.startswith(">")
                        or re.match(r'^[-*+]\s+', nxt) or re.match(r'^\d+\.\s+', nxt)
                        or re.match(r'^[-*_]{3,}\s*$', nxt)
                        or re.match(r'^\*\*[^*]+\*\*$', nxt)):
                    break
                para_lines.append(nxt)
                j += 1
            i = j
        else:
            i += 1

        text = " ".join(para_lines)
        flowables.append(Paragraph(inline_fmt(text), styles["body"]))


    flush_list()
    return flowables


# ── Cover page flowables ───────────────────────────────────────────────────────

def cover_page(title: str, subtitle: str, tagline: str, version_line: str,
               prepared_for: str | None = "Facyke-AI Agency") -> list:
    items = [
        Spacer(1, 62 * mm),   # below green header band
        Paragraph(title, styles["cover_title"]),
        Paragraph(subtitle, styles["cover_sub"]),
        Spacer(1, 4 * mm),
        HRFlowable(width="50%", thickness=2, color=GREEN,
                   hAlign='CENTER', spaceAfter=6),
        Spacer(1, 4 * mm),
        Paragraph(tagline, styles["cover_sub"]),
        Spacer(1, 6 * mm),
        Paragraph(version_line, styles["cover_ver"]),
    ]
    if prepared_for:
        items += [
            Spacer(1, 8 * mm),
            HRFlowable(width="30%", thickness=0.5, color=MUTED,
                       hAlign='CENTER', spaceAfter=4),
            Spacer(1, 4 * mm),
            Paragraph("Prepared for", styles["cover_ver"]),
            Spacer(1, 2 * mm),
            Paragraph(prepared_for, styles["cover_client"]),
        ]
    items.append(PageBreak())
    return items


# ── Build PDF ─────────────────────────────────────────────────────────────────

def build(src: Path, dst: Path, *, title: str, subtitle: str, tagline: str, version_line: str,
          pdf_title: str, pdf_subject: str, footer_title: str, band_text: str,
          prepared_for: str | None = "Facyke-AI Agency"):
    print(f"Reading {src} …")
    md = src.read_text(encoding="utf-8")

    # Strip YAML front matter if present
    md = re.sub(r'^---.*?---\s*', '', md, flags=re.DOTALL)

    doc = SimpleDocTemplate(
        str(dst),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=22 * mm,   # leave room for footer
        title=pdf_title,
        author="Facyke-AI Agency",
        subject=pdf_subject,
    )

    story = cover_page(title, subtitle, tagline, version_line, prepared_for)
    story += md_to_flowables(md)

    print("Building PDF …")
    doc.build(story, onFirstPage=make_first_page(band_text), onLaterPages=make_footer(footer_title))
    print(f"Saved: {dst}")
    print(f"Pages: check the PDF")


if __name__ == "__main__":
    base = Path(r"C:\Users\rigwe\Desktop\RemoteManagementSystem")

    build(
        base / "HANDOVER_GUIDE.md", base / "HANDOVER_GUIDE.pdf",
        title="Facyke RMM System", subtitle="Handover &amp; User Guide",
        tagline="Complete reference for all staff — from first login to advanced automation",
        version_line="Version 10.0 · September 2026",
        pdf_title="Facyke RMM System — Handover & User Guide",
        pdf_subject="Facyke RMM System — Staff handover and user guide",
        footer_title="Facyke RMM System — Handover & User Guide",
        band_text="Prepared for Facyke-AI Agency · Confidential · v10.0",
    )

    build(
        base / "TECHNICAL_GUIDE.md", base / "TECHNICAL_GUIDE.pdf",
        title="Facyke RMM System", subtitle="Technical Guide",
        tagline="Architecture, data models, API reference, and extension guide",
        version_line="Version 1.6 · September 2026",
        pdf_title="Facyke RMM System — Technical Guide",
        pdf_subject="Facyke RMM System — Developer and architect reference",
        footer_title="Facyke RMM System — Technical Guide",
        band_text="Prepared for Facyke-AI Agency · Confidential · v1.6",
    )
