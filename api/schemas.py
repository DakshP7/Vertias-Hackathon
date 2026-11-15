from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    age: int = Field(ge=0, le=120)
    sex: Literal["female", "male", "other"]
    contact: str = Field(default="", max_length=200)
    smoking_status: Literal["never", "former", "current", "unknown"] = "unknown"
    pack_years: float = Field(default=0, ge=0, le=300)
    family_history: bool = False
    conditions: str = Field(default="", max_length=2000)
    symptoms: str = Field(default="", max_length=2000)


class PatientOut(ORM):
    id: int
    display_id: str
    name: str
    age: int
    sex: str
    contact: str
    smoking_status: str
    pack_years: float
    family_history: bool
    conditions: str
    symptoms: str
    is_demo: bool
    created_at: datetime


class PatientListItem(PatientOut):
    status: str = "New"  # New | AI analysed | Under review | Report ready
    highest_risk: float | None = None
    highest_priority: str | None = None
    scan_count: int = 0


class VisitIn(BaseModel):
    visit_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=300)


class VisitOut(ORM):
    id: int
    visit_date: str
    reason: str


class AIResultOut(ORM):
    status: str
    risk_score: float | None
    priority: str | None
    uncertainty: str | None
    message: str
    model_version: str
    is_placeholder: bool
    threshold_high: float
    threshold_review: float
    has_heatmap: bool = False


class ScanOut(BaseModel):
    id: int
    patient_id: int
    scan_type: str
    uploaded_by: int
    uploaded_at: datetime
    result: AIResultOut | None
    disclaimer: str


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    scan_id: int | None = None


class NoteOut(BaseModel):
    id: int
    patient_id: int
    scan_id: int | None
    author_id: int
    author_name: str
    author_role: str
    text: str
    created_at: datetime


class ReportEdit(BaseModel):
    draft_text: str = Field(min_length=1, max_length=20000)


class ReportOut(ORM):
    id: int
    patient_id: int
    status: str
    source: str
    draft_text: str
    final_text: str | None
    created_by: int
    created_at: datetime
    approved_by: int | None
    approved_at: datetime | None
    disclaimer: str = ""


class ReviewIn(BaseModel):
    verdict: Literal["agree", "disagree", "needs_more"]
    note: str = Field(default="", max_length=2000)


class ReviewOut(BaseModel):
    id: int
    scan_id: int
    doctor_id: int
    doctor_name: str
    verdict: str
    note: str
    created_at: datetime


class EmailIn(BaseModel):
    recipient: str = Field(max_length=254, pattern=r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")


class EmailLogOut(ORM):
    id: int
    report_id: int
    recipient: str
    mode: str
    created_at: datetime


class DashboardOut(BaseModel):
    user_name: str
    user_role: str
    counts: dict[str, int]
    urgent: list[PatientListItem]
    recent_scans: list[dict]
    recent_activity: list[dict]
    email_mode: str
