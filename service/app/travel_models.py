"""출장정산 경계 모델. 입력은 항상 사용자가 확인하며 금액은 정수 원 단위다."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Situation(StrictModel):
    text: str = Field(min_length=1, max_length=3000)


class StageNote(StrictModel):
    version: int = Field(ge=1)
    stage: Literal['trip', 'evidence', 'review', 'calculate', 'draft', 'handoff']
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=5, max_length=2000)


class DemoPrepare(StrictModel):
    new_copy: bool = False


class OrganizationSettings(StrictModel):
    work_pattern: Literal["일반근무", "교대근무", "현업근무"] = "일반근무"
    note: str = Field(default="", max_length=1000)
    required_forms: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_forms(self):
        self.required_forms = [s.strip() for s in self.required_forms]
        if any(not s or len(s)>150 for s in self.required_forms) or len(set(self.required_forms))!=len(self.required_forms):
            raise ValueError("서식명은 중복 없이 1~150자로 입력하세요.")
        return self


class OrganizationCreate(OrganizationSettings):
    name: str = Field(min_length=2, max_length=150)
    organization_type: str = Field(min_length=2, max_length=80)
    region: str = Field(min_length=1, max_length=80)
    personnel_type: str = Field(min_length=2, max_length=80)


class OrganizationChange(OrganizationSettings):
    revision: int = Field(ge=1)


class RuleReview(StrictModel):
    revision: int = Field(ge=0)
    source_id: str = Field(min_length=1,max_length=40)
    location: str = Field(min_length=2,max_length=200)
    reviewer: str = Field(min_length=2,max_length=80)
    outcome: Literal['checked','needs_revision']
    note: str = Field(min_length=5,max_length=1000)
    original_checked: bool = False

    @model_validator(mode='after')
    def checked_original(self):
        if self.outcome=='checked' and not self.original_checked:
            raise ValueError('원문 대조 완료는 원본 확인 후 기록하세요.')
        return self


class TripCreate(StrictModel):
    organization_id: str
    work_pattern: Literal["일반근무", "교대근무", "현업근무"] = "일반근무"
    destination: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    transport: Literal["철도", "항공", "버스", "관용차", "개인차량", "기타"] = "철도"
    overnight: bool = True
    meals_provided: bool = False

    @model_validator(mode="after")
    def dates_valid(self):
        if self.end_date < self.start_date:
            raise ValueError("종료일은 시작일 이후여야 합니다.")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("데모는 366일 이내 출장만 지원합니다.")
        if self.overnight and self.end_date == self.start_date:
            raise ValueError("당일 출장은 숙박 없음으로 선택하세요.")
        return self


class EvidenceImport(StrictModel):
    version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=30000)
    source_type: Literal["card_sms", "receipt_text"] = "card_sms"


class TripChange(TripCreate):
    version: int = Field(ge=1)
    reason: str = Field(min_length=5,max_length=1000)
    preview_digest: str | None = Field(default=None,min_length=64,max_length=64)
    confirmed: bool = False


class Decision(StrictModel):
    version: int = Field(ge=1)
    decision: Literal["include", "exclude", "pending"]
    reason: str = Field(min_length=2, max_length=500)
    category: Literal["transport", "lodging", "meal", "other"]


class Version(StrictModel):
    version: int = Field(ge=1)


class LegalPackUpdate(Version):
    preview_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: bool = False
    reason: str = Field(min_length=5,max_length=500)


class IssueResolution(Version):
    reason: str = Field(min_length=5, max_length=500)


class TaskCreate(Version):
    workflow_revision: int = Field(ge=0)
    title: str = Field(min_length=3, max_length=180)
    note: str = Field(default="", max_length=1000)


class TaskChange(Version):
    workflow_revision: int = Field(ge=0)
    action: Literal["done", "reopen"]
    reason: str = Field(min_length=5, max_length=500)


class StageNoteTask(TaskCreate):
    context_confirmed: bool = False
    export_confirmed: bool = False


class DocumentConfirmation(Version):
    text: str = Field(min_length=1, max_length=30000)
    original_checked: bool = False
    reason: str = Field(min_length=5, max_length=500)


class LodgingNight(StrictModel):
    night: date
    region: Literal["seoul", "metropolitan", "other"]


class TrainingInput(StrictModel):
    entry_date: date
    completion_date: date
    teaching_dates: list[date] = Field(min_length=1, max_length=31)
    residential: bool = False
    dorm_available: bool = False
    settlement_method: Literal["actual", "fixed"] = "actual"
    institution_lodging: int = Field(default=0, ge=0, le=10000000)
    institution_meal: int = Field(default=0, ge=0, le=10000000)
    lunch_deduction: int = Field(default=0, ge=0, le=10000000)
    lunch_only_provided: bool = False
    notice_reference: str = Field(default="", max_length=300)
    notice_confirmed: bool = False
    costs_confirmed: bool = False
    zero_items: list[Literal["transport", "daily", "meal", "lodging"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def training_dates_valid(self):
        if self.completion_date < self.entry_date:
            raise ValueError("수료일은 입교일보다 앞설 수 없습니다.")
        if len(set(self.teaching_dates)) != len(self.teaching_dates):
            raise ValueError("교육일을 중복 입력할 수 없습니다.")
        if len(set(self.zero_items)) != len(self.zero_items):
            raise ValueError("미발생 항목을 중복 입력할 수 없습니다.")
        return self


class CalculationInput(Version):
    training: TrainingInput | None = None
    grade: Literal["group2", "group1", "unconfirmed"] = "unconfirmed"
    group1_standard_confirmed: bool = False
    journey_area: Literal["domestic", "overseas"] = "domestic"
    travel_scope: Literal["outside", "inside"] = "outside"
    conditions_confirmed: bool = False
    ordinary_fare_confirmed: bool = False
    lodging_scope_confirmed: bool = False
    lodging_not_claimed: bool = False
    lodging_nights: list[LodgingNight] = Field(default_factory=list, max_length=365)
    vehicle_dates: list[date] = Field(default_factory=list, max_length=366)
    within_minutes: int | None = Field(default=None, gt=0, le=1440)
    round_trip_km: Decimal | None = Field(default=None, ge=0, le=10000)
    assigned_vehicle: bool = False
    additional_review: bool = False

    @model_validator(mode="after")
    def unique_dates(self):
        nights=[n.night for n in self.lodging_nights]
        if len(nights)!=len(set(nights)) or len(self.vehicle_dates)!=len(set(self.vehicle_dates)):
            raise ValueError("같은 숙박일·차량 이용일을 중복 입력할 수 없습니다.")
        return self


class RuleCreate(StrictModel):
    pack_id: str
    title: str = Field(min_length=2, max_length=200)
    article: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=5, max_length=10000)
    effective_date: date
    expiry_date: date | None = None
    version: str = Field(min_length=1, max_length=40)
    # 등록만으로 실제 법적 효력을 인증하지 않는다. 로컬 데모는 합성/미검증만 허용한다.
    status: Literal["synthetic", "unverified"] = "unverified"

    @model_validator(mode="after")
    def dates_valid(self):
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("종료일(미포함)은 시행일보다 뒤여야 합니다.")
        return self
