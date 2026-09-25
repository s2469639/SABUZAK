"""부스 컨셉 자동 생성 결과 스키마. LLM이 반환한 JSON을 이 스키마로 검증한다."""

from typing import Literal

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


class ImageGeneration(BaseModel):
    prompt: str
    negative_prompt: str


class BoothConcept(BaseModel):
    booth_theme: BoothTheme
    selling_points: list[SellingPoint]
    event_plans: list[EventPlan]
    target_buyers: list[str]
    image_generation: ImageGeneration

    @field_validator("selling_points")
    @classmethod
    def _check_selling_points(cls, v):
        if len(v) != 3:
            raise ValueError("selling_points must contain exactly 3 items (핵심 2, 보조 1)")
        return v

    @field_validator("event_plans")
    @classmethod
    def _check_event_plans(cls, v):
        if not (3 <= len(v) <= 4):
            raise ValueError("event_plans must contain 3 to 4 items")
        return v

    @field_validator("target_buyers")
    @classmethod
    def _check_target_buyers(cls, v):
        if len(v) != 4:
            raise ValueError("target_buyers must contain exactly 4 items")
        return v
