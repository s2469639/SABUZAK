"""부스 컨셉 자동 생성 결과 스키마. LLM이 반환한 JSON을 이 스키마로 검증한다."""

from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class BoothTheme(BaseModel):
    title: str
    slogan: str
    description: str


class SellingPoint(BaseModel):
    badge: Literal["핵심", "보조"]
    title: str
    description: str


class EventPlan(BaseModel):
    id: str
    title: str
    tag: str
    schedule: str
    description: str


# --- [추가] 4대 핵심 UI용: 3초 · 30초 · 3분 (Visitor Journey) ---
class JourneyStage(BaseModel):
    headline: str
    goal: str
    message: str
    visitor_actions: list[str] = []


class VisitorJourney(BaseModel):
    sec3: JourneyStage   # 3초: 시선 사로잡기
    sec30: JourneyStage  # 30초: 흥미 및 탐색
    min3: JourneyStage   # 3분: 심층 상담 및 전환


# --- [추가] 3D 추천 및 백엔드 보존용 구조화 데이터 ---
class MerchandisingZone(BaseModel):
    name: str
    purpose: str


class MainVisualData(BaseModel):
    concept_ko: str
    concept_en: Optional[str] = None
    key_structure: Optional[str] = None


class MerchandisingData(BaseModel):
    zones: list[MerchandisingZone] = []
    display_flow: Optional[str] = None


class DemonstrationData(BaseModel):
    title: str
    scenario: Optional[str] = None


class Booth3DMetadata(BaseModel):
    main_visual: MainVisualData
    merchandising: MerchandisingData
    demonstration: DemonstrationData


class ImageGeneration(BaseModel):
    prompt: str
    negative_prompt: str


class BoothConcept(BaseModel):
    booth_theme: BoothTheme
    selling_points: list[SellingPoint]
    event_plans: list[EventPlan]
    target_buyers: list[str]
    image_generation: ImageGeneration
    
    # 신규 확장 항목 (기존 필드와 함께 안전하게 검증)
    visitor_journey: Optional[VisitorJourney] = None
    booth_3d: Optional[Booth3DMetadata] = None

    @field_validator("selling_points")
    @classmethod
    def _check_selling_points(cls, v):
        if len(v) != 3:
            raise ValueError("selling_points must contain exactly 3 items (핵심 2, 보조 1)")
        return v

    @field_validator("event_plans")
    @classmethod
    def _check_event_plans(cls, v):
        if len(v) != 3:
            raise ValueError("event_plans must contain exactly 3 items")
        return v

    @field_validator("target_buyers")
    @classmethod
    def _check_target_buyers(cls, v):
        if len(v) != 4:
            raise ValueError("target_buyers must contain exactly 4 items")
        return v