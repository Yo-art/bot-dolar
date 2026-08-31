"""
Bot de alertas de cotización de dólar (Fiwind vs Banco Supervielle) por Telegram.

Pensado para ejecutarse UNA VEZ por corrida (por ejemplo, disparado cada 10
minutos por GitHub Actions). Cada vez que corre: consulta la API pública de
ComparaDolar.ar, compara con el último valor guardado en
"ultima_cotizacion.json", y si compra o venta cambiaron en Fiwind o en Banco
Supervielle (o si cambió la Diferencia calculada), manda un mensaje a
Telegram con los valores y actualiza el archivo de estado.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ZONA_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

API_URL = "https://api.comparadolar.ar/usd"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultima_cotizacion.json")

# Palabras clave para identificar a cada proveedor dentro de la respuesta de
# la API (se busca en "slug" y en "nombre", sin importar mayúsculas).
PROVEEDORES = {
    "fiwind": {"claves": ["fiwind"], "etiqueta": "Fiwind"},
    "supervielle": {"claves": ["supervielle"], "etiqueta": "Banco Supervielle"},
}


# Distintas APIs nombran los precios de forma distinta. Probamos varias
# alternativas conocidas hasta encontrar una que tenga un valor numérico.
CLAVES_COMPRA = ["compra", "buy", "bid", "compraAhorro"]
CLAVES_VENTA = ["venta", "sell", "ask", "ventaAhorro"]


def _primer_valor(item, claves):
    for clave in claves:
        valor = item.get(clave)
        if valor is not None:
            return valor
    return None


def a_numero(valor):
    """Convierte compra/venta a float, soportando tanto números como strings
    con coma decimal (formato argentino, ej: '1.540,00')."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def obtener_cotizaciones():
    resp = requests.get(API_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Algunas APIs devuelven una lista directamente, otras la anidan en "rates".
    if isinstance(data, dict) and "rates" in data:
        data = data["rates"]

    resultado = {}
    for clave, info in PROVEEDORES.items():
        encontrado = None
        for item in data:
            texto = f"{item.get('slug', '')} {item.get('nombre', '')}".lower()
            if any(k in texto for k in info["claves"]):
                encontrado = item
                break
        if encontrado:
            compra = _primer_valor(encontrado, CLAVES_COMPRA)
            venta = _primer_valor(encontrado, CLAVES_VENTA)
            resultado[clave] = {"compra": compra, "venta": venta}
            if compra is None or venta is None:
                print(f"⚠️  No se pudo leer compra/venta para '{clave}'. Item completo: {encontrado}")
        else:
            print(f"⚠️  No se encontró proveedor para '{clave}' en la respuesta de la API.")
    return resultado


def cargar_estado():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_estado(actual, diferencia):
    estado = {"actual": actual, "diferencia": diferencia}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)


def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()


# Cuánto más barata es la venta para Supervielle Empleados respecto a la venta normal.
DESCUENTO_EMPLEADOS_VENTA = 19

# Cuánto se le suma a la compra normal de Supervielle para obtener la compra "Empleados".
AJUSTE_EMPLEADOS_COMPRA = 16


def calcular_derivados(actual):
    """Calcula la cotización 'Supervielle Empleados' (compra + ajuste, venta -
    descuento) y la diferencia entre la compra de Fiwind y esa venta."""
    sup = actual.get("supervielle", {})
    fw = actual.get("fiwind", {})

    sup_venta = a_numero(sup.get("venta"))
    sup_compra = a_numero(sup.get("compra"))

    empleados_venta = None
    if sup_venta is not None:
        empleados_venta = round(sup_venta - DESCUENTO_EMPLEADOS_VENTA, 2)

    empleados_compra = None
    if sup_compra is not None:
        empleados_compra = round(sup_compra + AJUSTE_EMPLEADOS_COMPRA, 2)

    fw_compra = a_numero(fw.get("compra"))

    diferencia = None
    if empleados_venta is not None and fw_compra is not None:
        diferencia = round(fw_compra - empleados_venta, 2)

    return {"compra": empleados_compra, "venta": empleados_venta}, diferencia


def formatear_diferencia(diferencia):
    if diferencia is None:
        return "N/D"
    signo = "+" if diferencia > 0 else ""
    if diferencia > 0:
        return f"🟢​🔼​ <b>{signo}{diferencia:.2f}</b> 🔼​🟢​"
    if diferencia < 0:
        return f"🔴🔽 <b>{diferencia:.2f}</b> 🔽🔴"
    return f"⚪ <b>{diferencia:.2f}</b>"


def formatear_mensaje(actual):
    fw = actual.get("fiwind", {})
    sup = actual.get("supervielle", {})
    empleados, diferencia = calcular_derivados(actual)
    ahora = datetime.now(ZONA_ARGENTINA).strftime("%d/%m/%Y %H:%M:%S")

    return (
        "🔔 <b>Cambio de cotización detectado</b>\n"
        f"🕒 {ahora}\n\n"
        "💱 <b>Fiwind</b>\n"
        f"  Compra: ${fw.get('compra', 'N/D')}\n"
        f"  Venta: ${fw.get('venta', 'N/D')}\n\n"
        "🏦 <b>Banco Supervielle</b>\n"
        f"  Compra: ${sup.get('compra', 'N/D')}\n"
        f"  Venta: ${sup.get('venta', 'N/D')}\n\n"
        "🏦 <b>Supervielle Empleados</b>\n"
        f"  Compra: ${empleados.get('compra', 'N/D')}\n"
        f"  Venta: ${empleados.get('venta', 'N/D')}\n\n"
        "📊 <b>Diferencia (Compra Fiwind − Venta Supervielle Empleados)</b>\n"
        f"  {formatear_diferencia(diferencia)}"
    )


def main():
    estado_anterior = cargar_estado()
    diferencia_anterior = estado_anterior.get("diferencia")
    actual_anterior = estado_anterior.get("actual")

    actual = obtener_cotizaciones()

    if not actual:
        print("No se pudo obtener ninguna cotización en esta corrida. No se hace nada.")
        return

    _, diferencia = calcular_derivados(actual)

    if diferencia is None:
        print("⚠️  No se pudo calcular la Diferencia en esta corrida (faltan datos). No se envía mensaje.")
        return

    # Avisamos si cambiaron las cotizaciones crudas (Fiwind o Supervielle) O
    # si cambió la Diferencia calculada. Esto evita que se "pierdan" avisos
    # cuando compra y venta de Supervielle cambian pero la Diferencia final
    # queda igual.
    hubo_cambio = (actual != actual_anterior) or (diferencia != diferencia_anterior)

    if hubo_cambio:
        enviar_telegram(formatear_mensaje(actual))
        guardar_estado(actual, diferencia)
        print(f"✅ Cambio detectado (Diferencia: {diferencia_anterior} -> {diferencia}) -> mensaje enviado.")
    else:
        guardar_estado(actual, diferencia)
        print(f"Sin cambios (Diferencia sigue en {diferencia}).")


if __name__ == "__main__":
    main()
