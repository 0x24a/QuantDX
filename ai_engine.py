from config import load_config_from_file, Config
from market_data import get_crypto_metrics
from openai import OpenAI
from jinja2 import Environment, FileSystemLoader, select_autoescape
from json import loads
from datetime import datetime
from retrying import retry

class AITradingEngine:
    def __init__(self, config: Config = load_config_from_file()) -> None:
        self.config = config
        self.openai = OpenAI(
            base_url=self.config.llm.provider,
            api_key=self.config.llm.api_key,
        )
        self.jinja2 = Environment(
            loader=FileSystemLoader("."),
            autoescape=select_autoescape()
        )
    
    def _render_prompt(self, balance: float, positions: list[dict] = []) -> str:
        market_datas = []
        for pair in self.config.trading.pairs:
            market_datas.append(get_crypto_metrics(pair))
        return self.jinja2.get_template(self.config.prompt).render(
            positions=positions,
            balance=balance,
            available_symbols=self.config.trading.pairs,
            market_datas=market_datas,
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    
    @retry
    def _get_decisions(self, prompt: str) -> dict:
        completion = self.openai.chat.completions.create(
            model=self.config.llm.model,
            messages=[
                {"role": "system", "content": "You are a professional crypto trader."},
                {"role": "user", "content": prompt}
            ]
        )
        assert completion.choices[0].message.content is not None
        return loads(completion.choices[0].message.content)