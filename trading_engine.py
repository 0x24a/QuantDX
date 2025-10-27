from typing import Optional
from ai_engine import AITradingEngine
from okx.Trade import TradeAPI
from okx.Account import AccountAPI
from config import load_config_from_file, Config
import requests
import datetime
import traceback
import time
import os

__VERSION__ = "2.1.0"
__PATCH__ = 2


class TradingEngine:
    def __init__(self, config: Config = load_config_from_file()):
        self.config = config
        self.ai_engine = AITradingEngine(self.config)
        self.trade_api = TradeAPI(
            api_key=self.config.trading.api_key,
            api_secret_key=self.config.trading.api_secret,
            passphrase=self.config.trading.passphrase,
            flag="1" if self.config.trading.sandbox else "0",
        )
        self.account_api = AccountAPI(
            api_key=self.config.trading.api_key,
            api_secret_key=self.config.trading.api_secret,
            passphrase=self.config.trading.passphrase,
            flag="1" if self.config.trading.sandbox else "0",
        )
        if not self.config.trading.sandbox:
            print("WARNING: Running in production mode, YOU ARE RISKING REAL MONEY.")

    def _discord_webhook(self, message: Optional[str] = None, json_data: Optional[dict] = None):
        if self.config.discord_webhook:
            if message:
                requests.post(self.config.discord_webhook, json={"content": message})
            if json_data:
                requests.post(self.config.discord_webhook, json=json_data)

    def _log(self, message: str):
        os.makedirs("logs", exist_ok=True)
        with open(
            "logs/" + datetime.datetime.now().strftime("%Y%m%d") + ".log", "a+"
        ) as f:
            message = (
                "["
                + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                + "] "
                + message
            )
            f.write(message + "\n")
            print(message)

    def _get_positions(self):
        data = self.account_api.get_positions()
        positions = []
        for position in data.get("data", []):
            symbol = position.get("instId")
            if float(position.get("pos", "0")) > 0:
                side = "LONG"
            elif float(position.get("pos", "0")) < 0:
                side = "SHORT"
            else:
                side = "NONE"
            lever = position.get("lever", 1.0)
            amount = (
                abs(float(position.get("pos", "0")))
                * float(lever)
                * float(position.get("last", "0"))
            )
            upnl = position.get("upl", 0.0)
            upnl_ratio = float(position.get("uplRatio", 0.0))*100
            self._log(f"Getting TP/SL data for position {symbol}")
            tp_sl_data = self.trade_api.get_algo_order_details(
                algoClOrdId=f"QuantDX{symbol.replace('-', '')}"
            ).get("data", [{}])[0]
            positions.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "lever": lever,
                    "amount": amount,
                    "upnl": upnl,
                    "upnl_ratio": upnl_ratio,
                    "tp": tp_sl_data.get("tpTriggerPx", None),
                    "sl": tp_sl_data.get("slTriggerPx", None),
                    "open_time": datetime.datetime.fromtimestamp(
                        int(tp_sl_data.get("cTime", 0)) / 1000.0, datetime.timezone.utc
                    )
                    .astimezone(datetime.timezone(datetime.timedelta(hours=8)))
                    .strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return positions

    def _get_balance(self, symbol: str = "USDT") -> float:
        data = self.account_api.get_account_balance()
        for balance in data.get("data", []):
            if balance["details"][0].get("ccy") == symbol:
                return float(balance["details"][0].get("availBal", 0))
        return 0.0

    def close_position(self, pair: str):
        self._log(f"Cancelling unfilled TP/SL order for {pair}")
        result = self.trade_api.cancel_algo_order(
            [{"instId": pair, "algoClOrdId": f"QuantDX{pair.replace('-', '')}"}]
        )  # i really really hate you okx
        self._log(f"Cancelled unfilled TP/SL order for {pair} with response: {result}")
        data = self.trade_api.close_positions(pair, "isolated", ccy="USDT")
        self._log(f"Closed position {pair} with response: {data}")
        return data

    def open_position(
        self, pair: str, side: str, amount: float, lever: float, tp: float, sl: float
    ):
        result = self.account_api.set_leverage(
            instId=pair, mgnMode="isolated", lever=lever
        )
        self._log(f"Set leverage for {pair} to {lever} with response: {result}")
        response = self.trade_api.place_order(
            instId=pair,
            tdMode="isolated",
            side=side,
            ordType="market",
            sz=amount,
            tgtCcy="quote_ccy",
            ccy="USDT",
            attachAlgoOrds=[
                {
                    "attachAlgoClOrdId": f"QuantDX{pair.replace('-', '')}",
                    "tpTriggerPx": tp,
                    "tpOrdPx": -1,
                    "slTriggerPx": sl,
                    "slOrdPx": -1,
                }
            ],
        )
        self._log(f"Placed order for {pair} with response: {response}")
        return response

    def trade(self):
        self._log("Running trade loop")
        balance = self._get_balance()
        self._log(f"Got balance: {balance}")
        positions = self._get_positions()
        self._log(f"Got positions: {positions}")
        prompt = self.ai_engine._render_prompt(balance, positions)
        self._log("Requesting decisions")
        decisions = self.ai_engine._get_decisions(prompt)
        self._log(f"Model thoughts: {decisions['think']}")
        self._log(f"Action Description: {decisions['desc']}")
        action_logs = []
        action_n = 1
        discord_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for decision in decisions["action"]:
            self._log(f"Running action {action_n}")
            self._log(f"Details: {decision}")
            if decision["type"] == "open_position":
                self.open_position(
                    pair=decision["pair"],
                    side=decision["side"],
                    amount=decision["amount"],
                    lever=decision["leverage"],
                    tp=decision["tp"],
                    sl=decision["sl"],
                )
                if decision['side'] == "buy":
                    action_logs.append({
                        "title": f"📈 BUY {decision['pair'].split('-')[0]}",
                        "description": f"{decision['desc']}\nConfidence: {decision['confidence']}",
                        "color": 4521728,
                        "timestamp": discord_ts
                    })
                elif decision['side'] == "sell":
                    action_logs.append({
                        "title": f"📉 SELL {decision['pair'].split('-')[0]}",
                        "description": f"{decision['desc']}\nConfidence: {decision['confidence']}",
                        "color": 16711680,
                        "timestamp": discord_ts
                    })
                action_n += 1
            elif decision["type"] == "close_position":
                self.close_position(pair=decision["pair"])
                action_logs.append({
                    "title": f"❌ CLOSE {decision['pair'].split('-')[0]}",
                    "description": f"{decision['desc']}\nConfidence: {decision['confidence']}",
                    "color": 3786171,
                    "timestamp": discord_ts
                })
                action_n += 1
        if action_logs:
            self._discord_webhook(json_data={
                "content": None,
                "embeds": action_logs,
                "attachments": []
            })

    def mainloop(self):
        self._discord_webhook(json_data={
            "content": None,
            "embeds": [
                {
                "title": "✅ Service Up",
                "description": f"Version: {__VERSION__} Patch {__PATCH__}",
                "color": 3786171
                }
            ],
            "attachments": []
            })
        self._log("Mainloop started")
        while True:
            try:
                self.trade()
            except Exception as e:
                self._log(
                    f"Serious error occurred: {e}, waiting for the next iteration"
                )
                self._log(traceback.format_exc())
            else:
                self._log("Trade completed, waiting for the next iteration")
            time.sleep(self.config.trading.trading_interval)
