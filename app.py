import os
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

app = Flask(__name__)

# Чтение ключей из настроек сервера Render
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Подключение к Bybit (Unified Account API)
session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET,
)

@app.route("/", methods=["GET"])
def home():
    return "Bybit Master Trader (Single Position & 20% Equity) is Running!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload provided"}), 400

    try:
        # Извлекаем и чистим тикер (убираем .P если пришел AKEUSDT.P)
        raw_symbol = data.get("symbol", "BTCUSDT")
        symbol = raw_symbol.replace(".P", "").upper()
        
        # Получаем действие: buy, close
        action = str(data.get("action", "")).lower()

        # Проверяем, есть ли вообще сейчас КАКИЕ-ЛИБО открытые позиции на аккаунте
        all_positions_info = session.get_positions(category="linear", settleCoin="USDT")
        positions_list = all_positions_info.get("result", {}).get("list", [])
        
        has_open_position = False
        current_open_symbol = None
        for pos in positions_list:
            if float(pos.get("size", 0)) > 0:
                has_open_position = True
                current_open_symbol = pos.get("symbol")
                break

        # 1. Попытка открыть новую сделку (Buy)
        if action == "buy":
            # Если уже есть открытая сделка по любой монете — блокируем вход
            if has_open_position:
                return jsonify({
                    "status": "ignored", 
                    "message": f"Position already open on {current_open_symbol}. New signal for {symbol} skipped."
                }), 200

            # Шаг А: Получаем баланс кошелька (USDT)
            wallet_balance = 0.0
            balance_info = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            coins_list = balance_info.get("result", {}).get("list", [])
            if coins_list:
                for coin in coins_list.get("coin", []):
                    if coin.get("coin") == "USDT":
                        wallet_balance = float(coin.get("equity", 0))
                        break
                if wallet_balance == 0.0 and "coin" in coins_list[0]:
                    for c in coins_list[0]["coin"]:
                        if c.get("coin") == "USDT":
                            wallet_balance = float(c.get("equity", 0))
                            break

            if wallet_balance <= 0:
                wallet_balance = float(coins_list[0].get("totalEquity", 100) or 100)

            # Шаг Б: Получаем текущую рыночную цену монеты
            ticker_info = session.get_tickers(category="linear", symbol=symbol)
            ticker_list = ticker_info.get("result", {}).get("list", [])
            if not ticker_list:
                return jsonify({"status": "error", "message": f"Could not fetch price for {symbol}"}), 400
            
            current_price = float(ticker_list[0].get("lastPrice", 0))
            if current_price <= 0:
                return jsonify({"status": "error", "message": "Invalid market price"}), 400

            # Шаг В: Считаем сумму позиции (20% от депозита * 5 плечо)
            target_usd_value = wallet_balance * 0.20 * 5
            raw_qty = target_usd_value / current_price
            qty = f"{raw_qty:.3f}"

            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty
            )
            return jsonify({
                "status": "success", 
                "action": "buy", 
                "symbol": symbol,
                "wallet_balance": wallet_balance,
                "calculated_qty": qty,
                "response": response
            }), 200

        # 2. Закрытие позиции по маркету (Close)
        elif action == "close":
            pos_info = session.get_positions(category="linear", symbol=symbol)
            positions = pos_info.get("result", {}).get("list", [])
            
            close_qty = "0"
            for pos in positions:
                if float(pos.get("size", 0)) > 0:
                    close_qty = pos.get("size")
                    break
            
            if float(close_qty) > 0:
                response = session.place_order(
                    category="linear",
                    symbol=symbol,
                    side="Sell",
                    orderType="Market",
                    qty=close_qty,
                    reduceOnly=True  # Флаг закрытия позиции
                )
                return jsonify({"status": "success", "action": "close", "symbol": symbol, "response": response}), 200
            else:
                return jsonify({"status": "ignored", "message": f"No open position found for {symbol} to close"}), 200

        else:
            return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
