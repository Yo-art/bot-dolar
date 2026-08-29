"""
Bot de alertas de cotización de dólar (Fiwind vs Banco Supervielle) por Telegram.

Pensado para ejecutarse UNA VEZ por corrida (por ejemplo, disparado cada 10
minutos por GitHub Actions). Cada vez que corre: consulta la API pública de
ComparaDolar.ar, compara con el último valor guardado en
"ultima_cotizacion.json", y si compra o venta cambiaron en Fiwind o en Banco
Supervielle, manda un mensaje a Telegram con los 4 valores y actualiza el
archivo de estado.
"""

import json
import os
from datetime import datetime

import requests

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


def obtener_cotizaciones():
    resp = requests.get(API_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    resultado = {}
    for clave, info in PROVEEDORES.items():
        encontrado = None
        for item in data:
            texto = f"{item.get('slug', '')} {item.get('nombre', '')}".lower()
            if any(k in texto for k in info["claves"]):
                encontrado = item
                break
        if encontrado:
            resultado[clave] = {
                "compra": encontrado.get("compra"),
                "venta": encontrado.get("venta"),
            }
        else:
            print(f"⚠️  No se encontró proveedor para '{clave}' en la respuesta de la API.")
    return resultado


def cargar_estado():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_estado(estado):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)


def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()


def formatear_mensaje(actual):
    fw = actual.get("fiwind", {})
    sup = actual.get("supervielle", {})
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return (
        "🔔 <b>Cambio de cotización detectado</b>\n"
        f"🕒 {ahora}\n\n"
        "💱 <b>Fiwind</b>\n"
        f"  Compra: ${fw.get('compra', 'N/D')}\n"
        f"  Venta: ${fw.get('venta', 'N/D')}\n\n"
        "🏦 <b>Banco Supervielle</b>\n"
        f"  Compra: ${sup.get('compra', 'N/D')}\n"
        f"  Venta: ${sup.get('venta', 'N/D')}"
    )


def main():
    anterior = cargar_estado()
    actual = obtener_cotizaciones()

    if not actual:
        print("No se pudo obtener ninguna cotización en esta corrida. No se hace nada.")
        return

    if actual != anterior:
        enviar_telegram(formatear_mensaje(actual))
        guardar_estado(actual)
        print("✅ Cambio detectado -> mensaje enviado y estado actualizado.")
    else:
        print("Sin cambios respecto a la última corrida.")


if __name__ == "__main__":
    main()
