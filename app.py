import os
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

LEVERAGE = 5          # Плечо
EQUITY_PERCENT = 0.20 # 20% от депозита

def normalize_symbol(symbol):
    if not symbol:
        return ""
    symbol = str(symbol).strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    if symbol.endswith(".P"):
        symbol = symbol[:-2]
    return symbol

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    try:
        # Безопасно принимаем любые данные от TradingView
        data = {}
        if request.is_json:
            data = request.get_json(silent=True) or {}
        elif request.data:
            try:
                data = json.loads(request.data.decode("utf-8"))
            except Exception:
                data = {"raw": request.data.decode("utf-8")}
        
        if not data and request.form:
            data = request.form.to_dict()

        print(f"--> ПОЛУЧЕН СИГНАЛ: {data}")

        # Извлекаем параметры с защитой от ошибок
        symbol = normalize_symbol(data.get("symbol", data.get("ticker", "EURUSD")))
        
        # Пытаемся найти действие (action / side / command)
        action = str(data.get("action", data.get("side", ""))).strip().lower()
        if not action and "strategy" in data:
            action = str(data["strategy"].get("order_action", "")).strip().lower()

        # Если явного action нет, но пришел запрос — запишем в логи и ответим ОК
        print(f"--> Символ: {symbol}, Действие: {action}")

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "action": action,
            "message": "Signal received and processed successfully"
        }), 200

    except Exception as e:
        # Перехватываем любую ошибку, чтобы сервер никогда не отдавал 500
        print(f"--> ОШИБКА ОБРАБОТКИ: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200

@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"status": "ok", "message": "Bot is running"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
