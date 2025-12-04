from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://foodplaner_user:foodplaner_password@db:5432/foodplaner"
    
    # API Keys
    spoonacular_api_key: str = ""
    anthropic_api_key: str = ""
    
    # App Settings
    daily_calorie_target: int = 1800
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
