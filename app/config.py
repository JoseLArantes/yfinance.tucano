from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = Field(
        validation_alias="DATABASE_URL"
    )
    default_api_username: str = Field(
        validation_alias="DEFAULT_API_USERNAME"
    )
    default_api_token: str = Field(
        validation_alias="DEFAULT_API_TOKEN"
    )
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8009, validation_alias="PORT")
    debug: bool = Field(default=True, validation_alias="DEBUG")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
