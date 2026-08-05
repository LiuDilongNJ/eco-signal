from sqlmodel import Field, SQLModel


class Message(SQLModel):
    """Generic message response."""
    message: str


class Token(SQLModel):
    """JSON payload containing access token."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(SQLModel):
    """Contents of JWT token."""
    sub: str | None = None
    type: str | None = None


class RefreshTokenPayload(SQLModel):
    """Contents of refresh JWT token."""
    sub: str
    jti: str
    family_id: str
    type: str


class NewPassword(SQLModel):
    """Schema for setting a new password."""
    token: str
    new_password: str = Field(min_length=8, max_length=128)
