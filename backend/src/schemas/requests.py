from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=100)


class Import(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: str | None = Field(default=None, min_length=1, max_length=180)
    csv: str = Field(min_length=1, max_length=1_000_000)
    source: str | None = None
    window_end: str | None = None
    version: str | int | float | None = None
    batch_uid: str | None = Field(default=None, max_length=120)
    expected_total: int | None = Field(default=None, ge=0, le=5000)
    expected_counts: dict[str, int] | None = None


class Declaration(BaseModel):
    window_end: str | None = Field(default=None, min_length=8, max_length=10)
    expected_total: int | None = Field(default=None, ge=0, le=5000)
    expected_counts: dict[str, int] | None = None
    reopen: bool = False


class IntakeBatch(BaseModel):
    model_config = ConfigDict(extra='allow')
    source: str | None = None
    window_end: str | None = Field(default=None, min_length=8, max_length=10)
    version: str | int | float | None = None
    csv: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    rows: list[dict[str, Any]] | None = None
    filename: str | None = Field(default=None, max_length=220)
    batch_uid: str | None = Field(default=None, max_length=120)
    upload_id: str | None = Field(default=None, max_length=120)
    client_token: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=120)
    declared_count: int | None = Field(default=None, ge=0, le=5000)
    expected_total: int | None = Field(default=None, ge=0, le=5000)
    expected_counts: dict[str, int] | None = None


class UploadSession(BaseModel):
    model_config = ConfigDict(extra='allow')
    upload_id: str | None = Field(default=None, max_length=120)
    source: str | None = None
    window_end: str | None = Field(default=None, max_length=10)
    version: str | int | float | None = None
    filename: str | None = Field(default=None, max_length=220)
    chunk_total: int | None = Field(default=None, ge=1, le=10000)


class Chunk(BaseModel):
    chunk: str = Field(min_length=1, max_length=200_000)


class Run(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True)
    dataset_id: int | None = Field(default=None, gt=0,
                                   validation_alias=AliasChoices('dataset_id', 'datasetId', 'data_version_id'))
    snapshot_id: int | None = Field(default=None, gt=0,
                                    validation_alias=AliasChoices('snapshot_id', 'snapshotId', 'window_snapshot_id'))
    options: dict = Field(default_factory=dict)


class Review(BaseModel):
    decision: Literal['approved', 'returned']
    note: str = Field(min_length=2, max_length=1000)


class Delivery(BaseModel):
    recipient: str = Field(min_length=2, max_length=100)
    cadence: Literal['once', 'daily']
    scheduled_at: datetime | None = None
