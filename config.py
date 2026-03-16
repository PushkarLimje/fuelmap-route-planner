# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    tomtom_key: str
    fuel_price_per_liter: float = 104.0   # ₹ per litre

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()