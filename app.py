import os
import json
import math

from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP


app = Flask(__name__)

API_KEY = os.environ.get("BYBIT_API_KEY")
API_SECRET = os.environ.get("BYBIT_API_SECRET")

session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)

# =========================
# НАСТРОЙКИ
# =========================

RISK_USD = 2.0
STOP_LOSS_PERCENT = 0.8


# =========================
# НОРМАЛИЗАЦИЯ СИМВОЛА
# =========================

def normalize_symbol(symbol):
    if not symbol:
        return ""

    symbol = str(symbol).strip().upper()

    # BYBIT:BTCUSDT.P -> BTCUSDT.P
    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    # BTCUSDT.P -> BTCUSDT
    if symbol.endswith(".P"):
        symbol = symbol[:-2]

    return symbol


# =========================
# ПОЛУЧЕНИЕ ПОЗИЦИИ
# =========================

def get_position(symbol):
    response = session.get_positions(
        category="linear",
        symbol=symbol
    )

    positions = response.get("result", {}).get("list", [])

    for position in positions:
        side = position.get("side", "")
        size = float(position.get("size", "0") or 0)

        if size > 0 and side in ["Buy", "Sell"]:
            return position

    return None


# =========================
# ПОЛУЧЕНИЕ ЦЕНЫ
# =========================

def get_price(symbol):
    response = session.get_tickers(
        category="linear",
        symbol=symbol
    )

    items = response.get("result", {}).get("list", [])

    if not items:
        raise Exception(f"Не удалось получить цену {symbol}")

    return float(items[0]["lastPrice"])


# =========================
# РАСЧЁТ РАЗМЕРА LONG
# =========================

def calculate_quantity(symbol, price):

    # $2 риска при стопе 0.8%
    stop_distance = price * (STOP_LOSS_PERCENT / 100)

    if stop_distance <= 0:
        raise Exception("Некорректная цена или стоп")

    raw_qty = RISK_USD / stop_distance

    # Получаем правила количества монеты
    response = session.get_instruments_info(
        category="linear",
        symbol=symbol
    )

    instruments = response.get("result", {}).get("list", [])

    if not instruments:
        raise Exception(
            f"Bybit не нашёл инструмент {symbol}"
        )

    lot_filter = instruments[0].get("lotSizeFilter", {})

    min_qty = float(
        lot_filter.get("minOrderQty", "0")
    )

    qty_step = float(
        lot_filter.get("qtyStep", "1")
    )

    if qty_step <= 0:
        qty_step = 1

    # Округляем вниз по шагу
    qty = math.floor(raw_qty / qty_step) * qty_step

    # Не меньше минимального количества
    if qty < min_qty:
        qty = min_qty

    return format(qty, ".12f").rstrip("0").rstrip(".")


# =========================
# ОТКРЫТИЕ LONG
# =========================

def open_long(symbol):

    # Проверяем, есть ли уже позиция
    position = get_position(symbol)

    if position:
        current_side = position.get("side")
        current_size = position.get("size")

        # Long уже открыт
        if current_side == "Buy":
            print(
                f"--> LONG УЖЕ ОТКРЫТ: "
                f"{symbol}, qty={current_size}"
            )

            return {
                "status": "already_open",
                "symbol": symbol,
                "side": "Buy",
                "qty": current_size
            }

        # Если вдруг остался старый Short,
        # сначала закрываем его
        if current_side == "Sell":

            print(
                f"--> НАЙДЕН SHORT {symbol}, "
                f"ЗАКРЫВАЕМ ЕГО ПЕРЕД LONG"
            )

            close_response = session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=str(current_size),
                reduceOnly=True,
                positionIdx=0
            )

            print(
                f"--> SHORT ЗАКРЫТ: "
                f"{close_response}"
            )

    # Получаем цену
    price = get_price(symbol)

    # Считаем количество под риск $2
    qty = calculate_quantity(symbol, price)

    print(f"--> ЦЕНА: {price}")
    print(f"--> РИСК: ${RISK_USD}")
    print(f"--> СТОП: {STOP_LOSS_PERCENT}%")
    print(f"--> LONG QTY: {qty}")

    # Открываем LONG
    response = session.place_order(
        category="linear",
        symbol=symbol,
        side="Buy",
        orderType="Market",
        qty=qty,
        timeInForce="GoodTillCancel",
        positionIdx=0
    )

    print(f"--> LONG ОТПРАВЛЕН: {response}")

    if response.get("retCode") != 0:
        raise Exception(
            response.get("retMsg", "Ошибка Bybit")
        )

    return {
        "status": "opened",
        "symbol": symbol,
        "side": "Buy",
        "qty": qty,
        "price": price,
        "risk_usd": RISK_USD
    }


# =========================
# ЗАКРЫТИЕ LONG
# =========================

def close_long(symbol):

    position = get_position(symbol)

    # НЕТ ПОЗИЦИИ
    if not position:

        print(
            f"--> SELL ПОЛУЧЕН, НО LONG "
            f"НЕ ОТКРЫТ: {symbol}"
        )

        print(
            "--> SHORT НЕ ОТКРЫВАЕМ"
        )

        return {
            "status": "nothing_to_close",
            "symbol": symbol,
            "message": "Long отсутствует, Short не открываем"
        }

    current_side = position.get("side")
    current_size = position.get("size")

    # На всякий случай не трогаем Short
    if current_side != "Buy":

        print(
            f"--> НАЙДЕН НЕ LONG: "
            f"{current_side} {symbol}"
        )

        print(
            "--> НИЧЕГО НЕ ОТКРЫВАЕМ"
        )

        return {
            "status": "ignored",
            "symbol": symbol,
            "message": "Обнаружена не Long-позиция"
        }

    print(
        f"--> ЗАКРЫВАЕМ LONG: "
        f"{symbol}, qty={current_size}"
    )

    response = session.place_order(
        category="linear",
        symbol=symbol,
        side="Sell",
        orderType="Market",
        qty=str(current_size),
        reduceOnly=True,
        positionIdx=0
    )

    print(
        f"--> LONG ЗАКРЫТ: {response}"
    )

    if response.get("retCode") != 0:
        raise Exception(
            response.get("retMsg", "Ошибка закрытия Bybit")
        )

    return {
        "status": "closed",
        "symbol": symbol,
        "side": "Sell",
        "qty": current_size
    }


# =========================
# WEBHOOK
# =========================

@app.route("/webhook", methods=["POST", "GET"])
def webhook():

    try:

        data = request.get_json(silent=True)

        if not data:

            if request.data:

                try:
                    data = json.loads(
                        request.data.decode("utf-8")
                    )

                except Exception:

                    data = {
                        "raw":
                        request.data.decode("utf-8")
                    }

            else:

                data = request.form.to_dict()

        print(
            f"--> ПОЛУЧЕН СИГНАЛ "
            f"ОТ TRADINGVIEW: {data}"
        )

        symbol = normalize_symbol(
            data.get("symbol", "")
        )

        action = str(
            data.get(
                "action",
                data.get("действие", "")
            )
        ).strip().lower()

        print(f"--> SYMBOL: {symbol}")
        print(f"--> ACTION: {action}")

        if not symbol:

            return jsonify({
                "status": "error",
                "message": "Не указан symbol"
            }), 400

        if not action:

            return jsonify({
                "status": "error",
                "message": "Не указан action"
            }), 400

        if action in [
            "buy",
            "купить",
            "long"
        ]:

            result = open_long(symbol)

            return jsonify(result), 200

        if action in [
            "sell",
            "продать",
            "exit",
            "close"
        ]:

            result = close_long(symbol)

            return jsonify(result), 200

        return jsonify({
            "status": "error",
            "message":
                f"Неизвестное действие: {action}"
        }), 400

    except Exception as e:

        print(
            f"--> ОШИБКА ОПЕРАЦИИ: {e}"
        )

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 200


# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET", "HEAD"])
def health():

    return jsonify({
        "status": "ok",
        "message": "Bybit bot is running"
    }), 200


# =========================
# ЗАПУСК
# =========================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
