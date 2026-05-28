"""Configuration loading from environment variables and YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchCriteria(BaseModel):
    titles: list[str] = [
        "Machine Learning Engineer",
        "ML Engineer",
        "Senior Machine Learning Engineer",
        "Staff Machine Learning Engineer",
        "Software Engineer, Machine Learning",
        "Software Engineer, AI",
        "AI/ML Engineer",
    ]
    keywords: list[str] = [
        "machine learning",
        "deep learning",
        "pytorch",
        "tensorflow",
        "LLM",
        "NLP",
        "computer vision",
        "MLOps",
        "model training",
    ]
    negative_keywords: list[str] = [
        "junior",
        "intern",
        "entry level",
        "new grad",
        "0-2 years",
        "1-3 years",
    ]
    locations: list[str] = ["Remote", "San Francisco, CA", "New York, NY", "Seattle, WA"]
    remote_ok: bool = True
    min_years_experience: int = 5
    max_years_experience: int = 15


class ScannerConfig(BaseModel):
    enabled: list[str] = [
        "linkedin",
        "indeed",
        "glassdoor",
        "greenhouse",
        "lever",
        "hn_hiring",
    ]
    results_per_search: int = 50
    hours_old: int = 72


class PipelineConfig(BaseModel):
    relevance_threshold: float = 0.6
    max_applications_per_run: int = 5
    delay_between_applications_seconds: int = 60
    dry_run: bool = False


class UserProfile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    website: str = ""
    github: str = ""
    current_company: str = ""
    current_title: str = ""


class NotificationConfig(BaseModel):
    email_to: str = ""
    email_from: str = ""
    send_on_new_matches: bool = True
    send_on_application: bool = True
    send_on_error: bool = True


class GreenhouseCompany(BaseModel):
    name: str
    board_token: str


class LeverCompany(BaseModel):
    name: str
    site: str


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets (from environment / GitHub Secrets)
    claude_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    greenhouse_api_key: str = ""
    lever_api_key: str = ""
    proxy_url: str = ""

    # Loaded from YAML
    search: SearchCriteria = SearchCriteria()
    scanner: ScannerConfig = ScannerConfig()
    pipeline: PipelineConfig = PipelineConfig()
    user_profile: UserProfile = UserProfile()
    notification: NotificationConfig = NotificationConfig()
    greenhouse_companies: list[GreenhouseCompany] = []
    lever_companies: list[LeverCompany] = []

    # Paths
    data_dir: str = "data"
    output_dir: str = "output"
    template_dir: str = "templates"


def load_config(
    config_path: str = "data/config.yml",
    companies_path: str = "data/companies.yml",
) -> AppConfig:
    """Load config from env vars + YAML files."""
    overrides: dict = {}

    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file) as f:
            yaml_data = yaml.safe_load(f) or {}
        if "search" in yaml_data:
            overrides["search"] = yaml_data["search"]
        if "scanner" in yaml_data:
            overrides["scanner"] = yaml_data["scanner"]
        if "pipeline" in yaml_data:
            overrides["pipeline"] = yaml_data["pipeline"]
        if "applier" in yaml_data and "user_profile" in yaml_data["applier"]:
            overrides["user_profile"] = yaml_data["applier"]["user_profile"]
        if "notification" in yaml_data:
            overrides["notification"] = yaml_data["notification"]

    companies_file = Path(companies_path)
    if companies_file.exists():
        with open(companies_file) as f:
            companies_data = yaml.safe_load(f) or {}
        if "greenhouse" in companies_data:
            overrides["greenhouse_companies"] = companies_data["greenhouse"]
        if "lever" in companies_data:
            overrides["lever_companies"] = companies_data["lever"]

    return AppConfig(**overrides)
