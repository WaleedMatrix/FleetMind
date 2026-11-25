"""Typed authentication and administration input and response contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)

Role = Literal["administrator", "engineer", "viewer"]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[a-z0-9][a-z0-9_.-]{2,63}$",
    ),
]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]
LoginPassword = Annotated[SecretStr, Field(min_length=1, max_length=128)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(StrictInput):
    username: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
    password: LoginPassword


class PasswordChange(StrictInput):
    current_password: LoginPassword
    new_password: Password


class AccountCreate(StrictInput):
    username: Username
    password: Password
    role: Role


class AccountUpdate(StrictInput):
    role: Role | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set or any(
            getattr(self, f) is None for f in self.model_fields_set
        ):
            raise ValueError("Provide a role or an activation status.")
        return self


class AccountInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    active: bool
    created_at: datetime


class CurrentUser(BaseModel):
    id: UUID
    username: str
    role: Role
    expires_at: datetime


class SessionInfo(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    current: bool


class AuditInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    actor_id: UUID | None
    target_id: UUID | None
    created_at: datetime


class ServiceCreate(StrictInput):
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=80,
            pattern=r"^[A-Za-z0-9_.-]+$",
        ),
    ]
    expires_in_days: Annotated[int, Field(strict=True, ge=1, le=90)] = 30


class ServiceInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class OrphanAction(StrictInput):
    action: Literal["adopt", "archive"]
    owner_id: UUID | None = None

    @model_validator(mode="after")
    def require_target_for_adoption(self):
        if (self.action == "adopt") != (self.owner_id is not None):
            raise ValueError("Adoption requires a destination owner.")
        return self


class OrphanInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    archived: bool
    created_at: datetime
