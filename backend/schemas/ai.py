"""Pydantic schemas for the AI toolkit endpoints."""

from typing import Optional

from pydantic import BaseModel, Field


class CaptionRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500, description="Video topic or title")
    language: str = Field(default="en", pattern=r"^(en|ur|roman_ur)$")
    styles: Optional[list[str]] = Field(
        default=None, description="Subset of caption styles to generate"
    )


class CaptionResponse(BaseModel):
    ok: bool = True
    captions: dict[str, str]
    disclaimer: str = "AI-generated text. Review before posting."


class HashtagRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    language: str = Field(default="en", pattern=r"^(en|ur|roman_ur)$")


class HashtagResponse(BaseModel):
    ok: bool = True
    primary: list[str] = []
    niche: list[str] = []
    broad: list[str] = []


class TranscribeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048, description="TikTok video URL")
    language: Optional[str] = Field(default=None, max_length=16)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    ok: bool = True
    text: str
    segments: list[TranscriptSegment] = []
    language: Optional[str] = None
    note: str = "Machine-generated transcript; it may contain errors."


class SummarizeRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=20000)
    url: Optional[str] = Field(default=None, max_length=2048)
    language: str = Field(default="en", pattern=r"^(en|ur|roman_ur)$")


class SummarizeResponse(BaseModel):
    ok: bool = True
    summary: str
    key_points: list[str] = []
    topics: list[str] = []
    keywords: list[str] = []
    disclaimer: str = "AI-generated analysis of the provided text — not verified facts."


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    target: str = Field(pattern=r"^(en|ur|roman_ur)$")


class TranslateResponse(BaseModel):
    ok: bool = True
    translated: str
    target: str
