"""Patient report drafting.

Privacy rules:
 - Only structured findings go to Gemini: no name, patient ID, contact details or images.
 - Doctor notes are scrubbed of the patient's own name/contact before sending.
 - If there is no API key, or Gemini fails, a fixed template report is used instead.
"""
import logging
import re

from ..config import DISCLAIMER, settings
from ..models import AIResult, Note, Patient, Scan, ScanReview, User

log = logging.getLogger("celliq")

SYSTEM_RULES = """You write a short, calm, plain-language summary for a patient, based ONLY on the findings supplied below.
Rules:
- Use only the supplied findings. Do not add any new diagnosis, numbers, or facts.
- Give no treatment advice and no prognosis.
- Do not say the patient has or does not have cancer. Say the scan was flagged or not flagged for review.
- Explain that an AI tool helped prioritise the scan and that a doctor reviewed the findings.
- If any result is marked as a placeholder or test result, say clearly that it is a demonstration only.
- Use simple words (reading age around 12). 150 to 250 words. No headings in markdown, plain paragraphs.
- End by telling the patient to discuss the results with their doctor."""


def _scrub(text: str, patient: Patient) -> str:
    """Remove the patient's own identifiers from free-text notes before sending out."""
    out = text
    for token in re.split(r"\s+", patient.name.strip()):
        if len(token) >= 2:
            out = re.sub(re.escape(token), "the patient", out, flags=re.IGNORECASE)
    if patient.contact:
        out = out.replace(patient.contact, "[contact removed]")
    out = re.sub(r"CIQ-\d+", "[id removed]", out, flags=re.IGNORECASE)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email removed]", out)
    out = re.sub(r"\+?\d[\d\s-]{7,}\d", "[number removed]", out)
    return out


VERDICT_TEXT = {"agree": "agreed with the AI result", "disagree": "disagreed with the AI result",
                "needs_more": "asked for further tests or imaging"}


def build_findings(patient: Patient, scans: list[tuple[Scan, AIResult | None]], notes: list[Note],
                   reviews: list[ScanReview] | None = None) -> str:
    lines = [
        f"Age: {patient.age}; sex: {patient.sex}",
        f"Smoking status: {patient.smoking_status}; pack-years: {(patient.pack_years or 0):g}",
        f"Family history of cancer: {'yes' if patient.family_history else 'no'}",
    ]
    if patient.symptoms:
        lines.append(f"Reported symptoms: {_scrub(patient.symptoms, patient)}")
    lines.append("Scans:")
    for scan, res in scans:
        kind = "chest CT" if scan.scan_type == "ct" else "tissue image"
        if res is None or res.status != "analysed":
            lines.append(f"- {kind}: could not be assessed by the AI tool")
        else:
            flag = "PLACEHOLDER/TEST RESULT. " if res.is_placeholder else ""
            lines.append(f"- {kind}: {flag}AI priority {res.priority}, confidence level {res.uncertainty}")
    if reviews:
        lines.append("Doctor review of the AI results:")
        for rv in reviews:
            extra = f" ({_scrub(rv.note, patient)})" if rv.note else ""
            lines.append(f"- A doctor {VERDICT_TEXT.get(rv.verdict, rv.verdict)}{extra}")
    if notes:
        lines.append("Doctors' notes:")
        for n in notes:
            lines.append(f"- {_scrub(n.text, patient)}")
    return "\n".join(lines)


def template_report(patient: Patient, scans: list[tuple[Scan, AIResult | None]], notes: list[Note],
                    reviews: list[ScanReview] | None = None) -> str:
    parts = [f"Summary for {patient.name} ({patient.display_id})", ""]
    parts.append("An AI tool was used to help prioritise your scan(s) so that a doctor could look at the most urgent ones first. "
                 "The tool does not make a diagnosis. A doctor has reviewed the results.")
    parts.append("")
    for scan, res in scans:
        kind = "chest CT scan" if scan.scan_type == "ct" else "tissue image"
        if res is None or res.status != "analysed":
            parts.append(f"Your {kind} could not be assessed by the AI tool and needs to be checked directly by a doctor.")
        else:
            test = " (this is a demonstration result only)" if res.is_placeholder else ""
            parts.append(f"Your {kind} was marked '{res.priority}' for review{test}.")
    if reviews:
        parts += ["", "Doctor review:"] + [f"- A doctor {VERDICT_TEXT.get(rv.verdict, rv.verdict)}." for rv in reviews]
    if notes:
        parts += ["", "Notes from your doctors:"] + [f"- {n.text}" for n in notes]
    parts += ["", "Please talk with your doctor about what these results mean for you and what happens next."]
    return "\n".join(parts)


def generate(patient: Patient, scans, notes, reviews=None) -> tuple[str, str]:
    """Returns (report_text, source) where source is 'gemini' or 'template'."""
    fallback = template_report(patient, scans, notes, reviews)
    if not settings.gemini_key:
        return fallback, "template"
    try:
        from google import genai  # imported lazily so the app runs without the package/key

        client = genai.Client(api_key=settings.gemini_key)
        prompt = f"{SYSTEM_RULES}\n\nFINDINGS:\n{build_findings(patient, scans, notes, reviews)}"
        resp = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        text = (resp.text or "").strip()
        if len(text) < 40:
            raise ValueError("Gemini returned an empty or very short response")
        return text, "gemini"
    except Exception as exc:  # network, quota, bad key, model name...
        log.warning("Gemini report failed (%s); using template.", type(exc).__name__)
        return fallback, "template"


def with_disclaimer(text: str) -> str:
    return f"{text}\n\n{DISCLAIMER}"
