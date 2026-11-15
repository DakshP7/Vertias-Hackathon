import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from ..config import DISCLAIMER


def report_pdf(display_id: str, patient_name: str, text: str, approved_by: str, approved_at: str) -> bytes:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=11, leading=16, spaceAfter=8)
    small = ParagraphStyle("s", parent=body, fontSize=9, leading=12, textColor=colors.grey)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm, title="CellIQ patient report")
    story = [
        Paragraph("CellIQ: Patient Report", ss["Title"]),
        Paragraph(f"Patient: {escape(patient_name)} ({escape(display_id)})", body),
        Paragraph(f"Approved by {escape(approved_by)} on {escape(approved_at)}", small),
        Spacer(1, 8),
    ]
    for para in text.split("\n"):
        story.append(Paragraph(escape(para) if para.strip() else "&nbsp;", body))
    story += [Spacer(1, 12), Paragraph(escape(DISCLAIMER), small)]
    doc.build(story)
    return buf.getvalue()
