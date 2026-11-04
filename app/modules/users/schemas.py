from datetime import datetime
from pydantic import EmailStr, Field, ConfigDict, model_validator
from app.core.schemas import StrictModel

class Register(StrictModel):
    model_config = ConfigDict(extra='ignore')  # untrusted role is discarded
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=150)

class Login(StrictModel):
    email: EmailStr
    password: str

class Profile(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    email: EmailStr | None = None
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=8)

    @model_validator(mode='after')
    def valid_change(self):
        if not self.model_fields_set:
            raise ValueError('At least one editable field is required')
        if bool(self.current_password) != bool(self.new_password):
            raise ValueError('Both password fields are required')
        return self

class UserOut(StrictModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class TokenOut(StrictModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserOut

class UserPage(StrictModel):
    items: list[UserOut]
    total: int
    page: int
    limit: int
    pages: int
