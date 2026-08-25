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
    return "Bybit Webhook Server is Running!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload provided"}), 400

    try:
        # Извлекаем и чистим тикер (убираем .P если пришел AKEUSDT.P)
        raw_symbol = data.get("symbol", "BTCUSDT")
        symbol = raw_symbol.replace(".P", "").upper()
        
        # Получаем действие: buy, sell, close
        action = str(data.get("action", "")).lower()

        # 1. Покупка / Открытие Long
        if action == "buy":
            qty = str(data.get("qty", ""))
            response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty
            )
            return jsonify({"status": "success", "action": "buy", "response": response}), 200

        # 2. Закрытие позиции по маркету
        elif action == "close":
            # Находим текущую открытую позицию на Bybit, чтобы узнать точное количество
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
                return jsonify({"status": "success", "action": "close", "response": response}), 200
            else:
                return jsonify({"status": "ignored", "message": "No open position found to close"}), 200

        # Если передали непонятное действие
        else:
            return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)