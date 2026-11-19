from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        size = len(value.get_secret_value().encode("utf-8"))
        if not 1 <= size <= 72:
            raise ValueError("Password must fit within 72 UTF-8 bytes.")
        return value


class Registration(Credentials):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("password")
    @classmethod
    def minimum_length(cls, value):
        if len(value.get_secret_value()) < 12:
            raise ValueError("Use at least 12 characters.")
        return value


class Profile(BaseModel):
    username: str
    email: EmailStr

