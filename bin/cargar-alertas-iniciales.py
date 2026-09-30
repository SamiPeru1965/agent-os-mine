#!/usr/bin/env python3
"""Carga las 7 alertas iniciales del Agent OS (retro W38) a la tabla Alertas de Budibase. Idempotente por Codigo_Flujo.

Uso: cargar-alertas-iniciales.py [--dry-run]
Exit: 0 ok / todas existían, 1 alguna falló, 2 env faltante o auth.
"""
import os, sys, json, gzip, pathlib, urllib.request, urllib.error

TABLE_ID = "ta_dcc7e496dfce434ea119cb3e749aa3a8"
ENV_FILE = pathlib.Path.home() / ".config/agent-os/env"

ALERTAS_INICIALES = [
    {
        "Codigo_Flujo": "WF005",
        "Vertical": "SmartCont",
        "Severidad": "🔴Critica",
        "Titulo": "Passwords en texto plano + OCR hardcodeado",
        "Descripcion": "Passwords de contadores guardados en texto plano en Google Sheets. Overrides de OCR hardcodeados por proveedor (riesgo de montos desactualizados cuando el proveedor cambia formato). 46+ días sin tocar desde 2026-08-03.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF001",
        "Vertical": "Hospitality",
        "Severidad": "🟡Alta",
        "Titulo": "Riesgo de SQL injection en Charlie House",
        "Descripcion": "Concatenación de strings en nodo Code antes de activar el flujo. Debe migrar a query parametrizada. 46+ días sin tocar.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF017",
        "Vertical": "RealEstate",
        "Severidad": "🟡Alta",
        "Titulo": "Fallback silencioso a fotos stock",
        "Descripcion": "Cuando falla el regex de extracción de fotos, cae a Unsplash sin logging ni alerta. Cliente puede recibir listing con fotos genéricas sin que nadie se entere.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF016",
        "Vertical": "RealEstate",
        "Severidad": "🟡Alta",
        "Titulo": "Placeholders sin configurar",
        "Descripcion": "Sheet ID, chat ID de soporte, email de soporte — todos con valores de template sin reemplazar. Bloquea deploy.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF014",
        "Vertical": "RealEstate",
        "Severidad": "🟡Alta",
        "Titulo": "Credenciales placeholder en template",
        "Descripcion": "Plantilla de terceros con credenciales placeholder sin rehacer. Bloquea activación segura.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF000",
        "Vertical": "TwinAgent",
        "Severidad": "🟢Media",
        "Titulo": "Slot reservado sin diseño ni JSON",
        "Descripcion": "SCI PersonalTwin Agent — placeholder en el catálogo, no hay diseño ni JSON todavía. No bloquea, pero degrada la coherencia del inventario.",
        "Estado": "Abierta",
        "Creada": "2026-08-03T00:00:00.000Z"
    },
    {
        "Codigo_Flujo": "WF009",
        "Vertical": "Hospitality",
        "Severidad": "🟡Alta",
        "Titulo": "Hotel Automate Booking sin tocar 28 días",
        "Descripcion": "Prox Accion abierta hace 28+ días. Cruzó umbral de 14 días. Verificar si Sheet ID y email de admin son valores reales o del template original.",
        "Estado": "Abierta",
        "Creada": "2026-08-26T00:00:00.000Z"
    }
]


class AuthError(Exception):
    pass


def cargar_env():
    # ponytail: solo líneas `export K=V` / `K=V`; el entorno existente tiene prioridad
    if ENV_FILE.is_file():
        for linea in ENV_FILE.read_text().splitlines():
            linea = linea.strip().removeprefix("export ").strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def api(method, path, body=None):
    req = urllib.request.Request(
        f"{os.environ['BUDIBASE_URL'].rstrip('/')}/api/public/v1{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={
            "x-budibase-api-key": os.environ["BUDIBASE_API_KEY"],
            "x-budibase-app-id": os.environ["BUDIBASE_APP_ID"],
            "Content-Type": "application/json; charset=utf-8",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read()[:300].decode("utf-8", "replace")
        if e.code in (401, 403):
            raise AuthError(f"HTTP {e.code}: {detalle}")
        raise RuntimeError(f"HTTP {e.code}: {detalle}")


def existe(codigo):
    r = api("POST", f"/tables/{TABLE_ID}/rows/search", {"query": {"equal": {"Codigo_Flujo": codigo}}})
    return bool(r.get("data"))


def crear(alerta):
    r = api("POST", f"/tables/{TABLE_ID}/rows", alerta)
    row_id = (r.get("data") or {}).get("_id")
    if not row_id:
        raise RuntimeError(f"respuesta sin data._id: {json.dumps(r, ensure_ascii=False)[:300]}")
    return row_id


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    cargar_env()
    faltan = [k for k in ("BUDIBASE_URL", "BUDIBASE_API_KEY", "BUDIBASE_APP_ID") if not os.environ.get(k)]
    if faltan:
        print(f"✗ faltan env vars: {', '.join(faltan)} (revisar {ENV_FILE})")
        return 2

    creadas = existian = fallaron = 0
    for alerta in ALERTAS_INICIALES:
        codigo = alerta["Codigo_Flujo"]
        try:
            if existe(codigo):
                print(f"⊘ {codigo} ya existe (skip)")
                existian += 1
            elif dry_run:
                print(f"→ {codigo} se crearía: [{alerta['Severidad']}] {alerta['Vertical']} — {alerta['Titulo']}")
                creadas += 1
            else:
                print(f"✓ {codigo} creada (rowId: {crear(alerta)})")
                creadas += 1
        except AuthError as e:
            print(f"✗ error de auth: {e}")
            return 2
        except Exception as e:
            print(f"✗ {codigo} error: {e}")
            fallaron += 1

    verbo = "se crearían" if dry_run else "creadas"
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}{creadas} {verbo}, {existian} ya existían, {fallaron} fallaron")
    return 1 if fallaron else 0


if __name__ == "__main__":
    sys.exit(main())
