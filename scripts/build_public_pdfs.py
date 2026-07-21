#!/usr/bin/env python3
"""Build the public Paritran solution document and technical white paper.

All product metrics are limited to File 2, Part B. The script is deterministic
apart from PDF metadata timestamps inserted by ReportLab.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
BLUE = colors.HexColor("#0A1F44")
TEAL = colors.HexColor("#2E7273")
GOLD = colors.HexColor("#A87229")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#526078")
PALE = colors.HexColor("#F3F6F8")
SOURCE_DIGEST = "800091205ad1e7c2a22a7add37f8d8fcfa1e5094f8737806bea56f5229fbc357"


styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=28, leading=33, textColor=BLUE, alignment=TA_LEFT, spaceAfter=8 * mm)
SUBTITLE = ParagraphStyle("Subtitle", parent=styles["Heading2"], fontName="Helvetica", fontSize=15, leading=20, textColor=TEAL, spaceAfter=6 * mm)
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=BLUE, spaceAfter=5 * mm)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=TEAL, spaceBefore=3 * mm, spaceAfter=2 * mm)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.3, leading=15.2, textColor=INK, spaceAfter=3.5 * mm)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8.4, leading=11.5, textColor=MUTED)
CALLOUT = ParagraphStyle("Callout", parent=BODY, fontName="Helvetica-Bold", fontSize=13, leading=18, textColor=BLUE, leftIndent=5 * mm, borderColor=GOLD, borderWidth=0, borderPadding=3 * mm)
CENTER = ParagraphStyle("Center", parent=SMALL, alignment=TA_CENTER)


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return [Paragraph(f"• {item}", BODY) for item in items]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D8E0E7"))
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 10 * mm, "Paritran | PS-69EEFE4F8CD1C | Team Paritran")
    canvas.drawRightString(190 * mm, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def metric_table():
    rows = [
        ["Measure", "Result", "Boundary"],
        ["Linkage P / R / F1", "0.957 / 0.966 / 0.962", "Synthetic ground truth"],
        ["Money trail", "90.8 percent", "Directed reachability"],
        ["Legal mapping", "100 percent, 8/8 and 15/15", "Only when three paths agree"],
        ["BM25 floor", "52.4 percent", "Condensed v1 corpus"],
        ["F9 stub", "40 / 10 / 0", "Passed / withheld / leaked"],
        ["F9 live gemma", "5 / 1 / 0", "Passed / withheld / leaked"],
        ["NER P / R", "0.74 / 1.0", "Rule-augmented identifiers"],
        ["Scale", "297 complaints, 6/6 networks", "Synthetic data"],
        ["Custody", "Verified and tamper-evident", "Not immutable against full rewrite"],
    ]
    table = Table(rows, colWidths=[42 * mm, 62 * mm, 66 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("LEADING", (0, 0), (-1, -1), 11.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def cover(title, subtitle, label):
    return [
        Spacer(1, 22 * mm),
        p("KRISEVA AI | KANAD S.H.I.E.L.D. 2026", ParagraphStyle("Eyebrow", parent=SMALL, fontName="Helvetica-Bold", fontSize=9.5, textColor=GOLD)),
        Spacer(1, 10 * mm),
        p(title, TITLE),
        p(subtitle, SUBTITLE),
        Spacer(1, 16 * mm),
        p("From complaint to conviction", ParagraphStyle("Statement", parent=CALLOUT, fontSize=19, leading=24)),
        Spacer(1, 18 * mm),
        p(f"{label}<br/>Category 2 student team | ID 10_338<br/>PS-69EEFE4F8CD1C | Cyber Crime Branch, Ahmedabad City", BODY),
        Spacer(1, 18 * mm),
        p("Truth boundary", H2),
        p("Working prototype measured on synthetic data. No real deployment, external institution validation, autonomous legal decision, or production admissibility claim is made.", BODY),
        Spacer(1, 12 * mm),
        p(f"Canonical claim source SHA-256<br/>{SOURCE_DIGEST}", SMALL),
    ]


def build_solution():
    out = ROOT / "Paritran_Solution_Document.pdf"
    story = cover("Paritran", "Auditable cyber-fraud investigation support on government-controlled hardware", "SOLUTION DOCUMENT")
    story += [PageBreak(), p("1. Problem and scope", H1), p("Detection, freezing, and registry systems are essential. Investigators still need to join related complaints, reconstruct the path of funds, map cited law, and preserve a reviewable custody record. Paritran addresses that operational handoff."), p("The product assists an officer. It does not name a person guilty, certify evidence, or replace legal review.", CALLOUT), p("Build state", H2)]
    story += bullets(["Full prototype completed across ten milestones.", "191 tests passing in the recorded build state.", "Public repository and GitHub Pages publication.", "Synthetic demonstration data only, with zero real PII."])
    story += [p("Team", H2), p("Ayush Tiwary: architecture, grounding, audit core, legal mapping, and on-premise build.<br/>Aditya Arora: graph analytics, money trail, synthetic data, dashboard, and frontend."), PageBreak(), p("2. System design", H1)]
    story += bullets(["Ingest: hash every input and attach source identity.", "Resolve: extract identifiers and join complaints by shared infrastructure.", "Link: surface candidate syndicate networks with graph methods.", "Trace: follow value through the directed ledger toward cash-out.", "Map: combine rules, BM25, and InLegalBERT; abstain on disagreement.", "Draft: produce cited language behind the F9 groundedness gate.", "Preserve: append every action to a tamper-evident custody chain.", "Review: require officer acceptance, rejection, and sign-off."])
    story += [p("Design doctrine", H2), p("The deterministic core never treats generated prose as evidence. The language layer may draft, but source checks and human review govern release."), PageBreak(), p("3. Canonical measured results", H1), p("All performance and scale results below are the File 2, Part B values. Network and linkage results use synthetic ground truth and must be described that way."), metric_table(), Spacer(1, 5 * mm), p("Precision via abstention", H2), p("The legal-mapping result is not a blanket accuracy claim. It is 100 percent only on the high-confidence subset where three independent paths agree: 8/8 and 15/15. All other cases route to a human officer."), PageBreak(), p("4. Evidence, custody, and security", H1)]
    story += bullets(["Every input and output receives a SHA-256 digest.", "Custody is hash-chained and verified; silent edits break verification.", "A hash chain is tamper-evident, not magically immutable against a privileged full rewrite.", "The F9 gate withholds unsupported drafted claims.", "Role-based access and human sign-off preserve accountability.", "The demo is designed for local operation. Offline state is verified by the operator and environment, not inferred from marketing copy.", "Current Python dependency audit runs without advisory suppressions."])
    story += [p("Legal boundary", H2), p("Paritran can draft and pre-fill a Section 63 packet with citations and integrity material. Named custodians and qualified reviewers remain responsible for review and signature. Counsel-approved admissibility remains TODO-VERIFY."), PageBreak(), p("5. Pilot and verification", H1), p("A pilot should run on government-controlled hardware with an approved data-custody plan, an offline operating procedure, named roles, acceptance criteria, rollback, and a signed verification receipt."), p("Minimum acceptance checks", H2)]
    story += bullets(["Reproduce the canonical synthetic run without changing the frozen baseline.", "Verify linkage, money trail, F9, NER, and custody outputs against the receipt.", "Exercise role boundaries, export review, rejection paths, and recovery.", "Record network posture and physical controls at the venue.", "Do not introduce real complainant data until authority, minimisation, retention, and deletion rules are approved."])
    story += [p("Known limitations", H2), p("Real-institution validation, production data integration, counsel-approved certificate wording, production key custody, and third-party operational acceptance remain TODO-VERIFY."), Spacer(1, 8 * mm), p("Repository: github.com/ayushtiwary-ops/paritran<br/>Site: ayushtiwary-ops.github.io/paritran<br/>Contact: aloolifts@gmail.com", BODY)]
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title="Paritran Solution Document", author="Team Paritran")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_white_paper():
    out = ROOT / "docs" / "Paritran_White_Paper.pdf"
    story = cover("Paritran technical white paper", "A deterministic investigation core with a fenced language layer", "TECHNICAL WHITE PAPER")
    story += [PageBreak(), p("Abstract", H1), p("Paritran is an on-premise cyber-fraud investigation prototype that links synthetic complaints into candidate mule networks, reconstructs a directed money trail, maps cited legal sections through agreement and abstention, gates drafted claims against source text, and records actions in a tamper-evident custody chain. The system is designed to assist an officer, never to decide guilt or certify admissibility."), p("The canonical synthetic run contains 297 complaints and six planted networks. The measured linkage precision, recall, and F1 are 0.957, 0.966, and 0.962; directed reachability traces 90.8 percent of value to cash-out. Legal mapping reports 100 percent only on high-confidence three-path agreement subsets of 8/8 and 15/15, with a 52.4 percent BM25 floor. These results are bounded measurements, not deployment evidence."), p("1. Requirements", H1)]
    story += bullets(["Keep complaint data and models under department control.", "Make every result reviewable and source-linked.", "Separate deterministic findings from generated language.", "Abstain rather than promote disagreement to a legal conclusion.", "Preserve a verifiable custody trail and explicit operator decisions."])
    story += [PageBreak(), p("2. Architecture", H1), p("Paritran uses a deterministic graph and rules core behind local APIs. A separately fenced language component may draft cited text. Generated text cannot alter graph facts, custody records, or deterministic results."), p("Complaint-to-entity linkage", H2), p("Identifiers extracted from synthetic complaint text resolve to shared entities. A graph joins complaints through common phones, devices, accounts, and other infrastructure. Communities become review candidates, not automatic allegations."), p("Money trail", H2), p("A directed ledger represents movement from victims through mule layers toward cash-out. The 90.8 percent value-traced result is reachability over this synthetic ledger."), p("Human control", H2), p("Operators see source records, confidence posture, and the reason for abstention. Acceptance and rejection are explicit workflow actions."), PageBreak(), p("3. Legal mapping and grounded drafting", H1), p("Rules, BM25 retrieval, and InLegalBERT each propose legal sections. Only agreement enters the high-confidence subset. Disagreement routes to an officer. This is precision via abstention, not a claim of universal correctness."), p("Measured mapping boundary", H2), p("High-confidence agreement measured 100 percent on 8/8 and 15/15 cases. The BM25 v1 floor is 52.4 percent. Frozen benchmark values remain tied to their recorded environment; a dependency change requires re-measurement before equivalence is claimed."), p("F9 groundedness gate", H2), p("The deterministic stub run recorded 40 claims passed, 10 withheld, and zero leaked. The live local gemma run recorded five passed, one withheld, and zero leaked. The gate checks support, but it does not replace legal review."), PageBreak(), p("4. Experimental protocol and results", H1), p("The demonstration uses synthetic data with planted ground truth and zero real PII. This permits direct measurement of linkage against a known answer key while avoiding a false claim of real-institution validation."), metric_table(), PageBreak(), p("5. Custody and security", H1)]
    story += bullets(["SHA-256 digests bind artifacts and records.", "An append-only hash chain makes local edits detectable.", "The chain head must be anchored outside the database to strengthen rewrite detection.", "Role boundaries and explicit sign-off keep the officer accountable.", "Local deployment reduces external dependency, but the operator must verify the actual network posture.", "Dependency audit runs without advisory suppression in CI.", "Synthetic-only publication prevents exposure of real complainant data."])
    story += [p("Security non-claims", H2), p("The prototype does not claim an HSM-backed production signing ceremony, independently certified isolation, real-data penetration testing, or immunity from a fully privileged host attacker. Those controls belong to a scoped pilot acceptance plan."), PageBreak(), p("6. Limitations, deployment, and conclusion", H1), p("Limitations", H2)]
    story += bullets(["Synthetic results do not establish performance on a police or bank dataset.", "The high-confidence legal result applies only to the stated agreement subsets.", "Tamper-evident does not mean immutable against full privileged rewrite.", "Drafting assistance does not establish admissibility or legal correctness.", "Production key custody, retention, deletion, and external anchoring remain TODO-VERIFY."])
    story += [p("Pilot path", H2), p("A pilot should use government-controlled hardware, approved source data, named operators, deterministic acceptance tests, rollback, physical verification, and signed custody receipts. Real data must remain outside the prototype until authority and minimisation controls are approved."), p("Conclusion", H2), p("Paritran's contribution is not another opaque score. It is a narrow, reproducible path from linked synthetic complaints to a reviewable money trail, cited legal suggestions, a grounded drafting gate, and verifiable custody, with abstention and human authority preserved."), Spacer(1, 8 * mm), p(f"Canonical claim source: KANAD_SHIELD_2026_02_SOLUTION_DOSSIER.md<br/>SHA-256: {SOURCE_DIGEST}", SMALL)]
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title="Paritran Technical White Paper", author="Team Paritran")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build_solution()
    build_white_paper()
