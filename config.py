from typing import Optional
from pydantic import BaseModel
import json

class TradingConfig(BaseModel):
    api_key: str
    api_secret: str
    passphrase: str
    sandbox: bool
    pairs: list[str]
    trading_interval: int

class LLMConfig(BaseModel):
    provider: str
    api_key: str
    model: str

class Config(BaseModel):
    trading: TradingConfig
    llm: LLMConfig
    discord_webhook: Optional[str]
    prompt: str

def load_config_from_file(path: str = ".secrets.env.json") -> Config:
    with open(path, "r") as f:
        config = json.load(f)
    return Config(**config)