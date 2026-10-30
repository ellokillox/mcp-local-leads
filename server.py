#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp-local-leads — servidor MCP (Model Context Protocol) de stdio, sin dependencias.
================================================================================
Expone una herramienta que un cliente de IA (Claude Desktop, Claude Code, Cursor,
Windsurf, Continue, Hermes...) puede llamar para encontrar negocios locales que
aparecen en Google Maps **pero no tienen sitio web**: la lista de prospectos mas
obvia que existe para una agencia o consultor que vende webs, SEO o marketing.

  Herramientas
  ------------
  find_businesses_without_website  Busca en Google Places API (New) por texto,
                                   pagina hasta N paginas, quita duplicados por
                                   placeId y devuelve SOLO los negocios sin
                                   `websiteUri`.
  export_leads_csv                 Guarda esos prospectos en un CSV (lo que el
                                   cliente de IA acaba de encontrar, en disco).

  Por que es util y por que es tan simple
  ---------------------------------------
  El paso que se automatiza aqui es el que nadie hace a mano: revisar negocio por
  negocio si tiene web. Places ya trae el dato (`websiteUri`); lo que falta es
  filtrarlo, paginar y devolverlo limpio. Eso es todo lo que hace este servidor.

  Instalacion
  -----------
    python3 server.py            # protocolo JSON-RPC 2.0 por stdio, una linea por mensaje

  Variables de entorno
  --------------------
    GOOGLE_PLACES_API_KEY   (obligatoria) clave de Places API (New) con facturacion.
    PLACES_BASE_URL         (opcional)  base alternativa, para pruebas con un mock.
    PLACES_TIMEOUT          (opcional)  segundos por peticion HTTP (por defecto 30).

  Solo libreria estandar: Python 3.8+ en Windows, macOS y Linux. Sin pip, sin node.

  Licencia MIT.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVER_NAME = "mcp-local-leads"
SERVER_VERSION = "1.0.0"
PROTOCOL_DEFAULT = "2025-06-18"
PROTOCOL_SUPPORTED = {"2024-11-05", "2025-03-26", "2025-06-18"}

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
# Mascara de campos deliberadamente estrecha: solo lo que se devuelve. Places
# factura por SKU segun los campos pedidos, asi que pedir de mas cuesta mas.
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "places.primaryTypeDisplayName",
    "places.businessStatus",
    "places.location",
    "nextPageToken",
])

CSV_COLUMNS = ["place_id", "nombre", "direccion", "ciudad", "telefono",
               "rating", "resenas", "tipo", "estado", "maps_url", "lat", "lng"]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    """Los logs van a stderr: stdout es exclusivamente JSON-RPC."""
    print(f"[mcp-local-leads] {msg}", file=sys.stderr, flush=True)


def to_int(value, default: int, minimo: int, maximo: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimo, min(maximo, n))


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def locality_from_address(address: str, fallback: str = "") -> str:
    """La ciudad es la PENULTIMA parte de formattedAddress: Google termina en el pais.

    'Av. Providencia 123, Providencia, Región Metropolitana, Chile' -> 'Región Metropolitana'
    """
    partes = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(partes) >= 2:
        return partes[-2]
    return fallback or (partes[0] if partes else "")


def normalize(place: dict, ciudad_pedida: str) -> dict:
    """Convierte un `place` de Places API (New) a un registro plano y estable."""
    display = place.get("displayName") or {}
    tipo = (place.get("primaryTypeDisplayName") or {}).get("text") or ""
    loc = place.get("location") or {}
    address = place.get("formattedAddress") or ""
    return {
        "place_id": place.get("id") or "",
        "nombre": display.get("text") or "",
        "direccion": address,
        "ciudad": locality_from_address(address, ciudad_pedida),
        "telefono": place.get("nationalPhoneNumber") or "",
        "rating": place.get("rating"),
        "resenas": place.get("userRatingCount"),
        "tipo": tipo,
        "estado": place.get("businessStatus") or "",
        "maps_url": place.get("googleMapsUri") or "",
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "has_website": bool(place.get("websiteUri")),
    }


# ---------------------------------------------------------------------------
# Google Places API (New)
# ---------------------------------------------------------------------------
class PlacesError(RuntimeError):
    pass


def places_search(text_query: str, page_token: str | None, page_size: int,
                  language: str | None, api_key: str) -> dict:
    base = os.environ.get("PLACES_BASE_URL", "").strip() or "https://places.googleapis.com"
    url = base.rstrip("/") + "/v1/places:searchText"
    body = {"textQuery": text_query, "pageSize": page_size}
    if page_token:
        body["pageToken"] = page_token
    if language:
        body["languageCode"] = language
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}",
    }
    timeout = to_float(os.environ.get("PLACES_TIMEOUT"), 30.0)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read()[:400].decode("utf-8", "replace")
        raise PlacesError(f"Places API respondio HTTP {e.code}: {detalle}") from None
    except urllib.error.URLError as e:
        raise PlacesError(f"No se pudo conectar con Places API: {e.reason}") from None
    except json.JSONDecodeError:
        raise PlacesError("Places API devolvio una respuesta que no es JSON") from None


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------
def tool_find(args: dict) -> dict:
    ciudad = str(args.get("city") or args.get("ciudad") or "").strip()
    nicho = str(args.get("niche") or args.get("nicho") or "").strip()
    if not ciudad:
        return {"error": "Falta el parametro obligatorio `city` (por ejemplo \"Temuco, Chile\")."}
    pais = str(args.get("country") or "").strip()
    limite = to_int(args.get("limit"), 20, 1, 60)
    por_pagina = to_int(args.get("page_size"), 20, 1, 20)
    max_paginas = to_int(args.get("max_pages"), 3, 1, 3)
    idioma = str(args.get("language") or "").strip() or None

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        return {"error": "Falta la variable de entorno GOOGLE_PLACES_API_KEY "
                         "(clave de Places API (New) con facturacion activa)."}

    nicho_txt = nicho or "negocios locales"
    lugar = ciudad if (not pais or ciudad.lower().endswith(pais.lower())) else f"{ciudad}, {pais}"
    consulta = f"{nicho_txt} in {lugar}"

    vistos: set[str] = set()
    sin_web: list[dict] = []
    con_web = 0
    total_negocios = 0
    token: str | None = None
    peticiones = 0
    paginas_leidas = 0

    while paginas_leidas < max_paginas:
        payload = places_search(consulta, token, por_pagina, idioma, api_key)
        peticiones += 1
        paginas_leidas += 1
        places = payload.get("places") or []
        for p in places:
            reg = normalize(p, ciudad)
            if not reg["place_id"] or reg["place_id"] in vistos:
                continue
            vistos.add(reg["place_id"])
            total_negocios += 1
            if reg["has_website"]:
                con_web += 1
                continue
            sin_web.append(reg)
            if len(sin_web) >= limite:
                break
        token = payload.get("nextPageToken")
        if len(sin_web) >= limite or not token or not places:
            break

    for r in sin_web:
        r.pop("has_website", None)

    return {
        "query": consulta,
        "city": ciudad,
        "niche": nicho or None,
        "businesses_seen": total_negocios,
        "with_website": con_web,
        "without_website": len(sin_web),
        "requests": peticiones,
        "pages": paginas_leidas,
        "next_page_token": token,
        "leads": sin_web,
    }


def tool_export_csv(args: dict) -> dict:
    leads = args.get("leads")
    if not isinstance(leads, list) or not leads:
        return {"error": "Pasa `leads`: la lista devuelta por find_businesses_without_website."}
    destino = str(args.get("path") or "local-leads.csv").strip()
    path = Path(os.path.expanduser(destino))
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            w.writeheader()
            n = 0
            for lead in leads:
                if isinstance(lead, dict):
                    w.writerow(lead)
                    n += 1
    except OSError as e:
        return {"error": f"No se pudo escribir {path}: {e}"}
    return {"path": str(path.resolve()), "rows": n}


TOOLS = [
    {
        "name": "find_businesses_without_website",
        "description": (
            "Find local businesses that appear in Google Maps but have NO website, in any city. "
            "Useful to build a prospect list for web design, SEO or marketing services. "
            "Uses Google Places API (New) Text Search, paginates, removes duplicates by placeId and "
            "returns only the businesses whose `websiteUri` is empty."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string",
                         "description": "City to search, e.g. \"Temuco, Chile\" or \"Austin, TX\"."},
                "niche": {"type": "string",
                          "description": "Business type, e.g. \"dental clinics\", \"plumbers\", \"restaurants\". "
                                         "Optional: without it, searches generic local businesses."},
                "country": {"type": "string",
                            "description": "Country name or code appended to the query when the city "
                                           "does not include it (e.g. \"Chile\", \"CL\"). Optional."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20,
                          "description": "Maximum number of businesses WITHOUT a website to return."},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 20, "default": 20,
                              "description": "Results per Places request (max 20, Google's cap)."},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3,
                              "description": "How many Places pages to read (each page is a billed request)."},
                "language": {"type": "string",
                             "description": "Optional languageCode for results, e.g. \"es\", \"en\"."},
            },
            "required": ["city"],
            "additionalProperties": False,
        },
    },
    {
        "name": "export_leads_csv",
        "description": (
            "Save the leads returned by find_businesses_without_website to a CSV file on disk "
            "(12 columns, UTF-8 with BOM so Excel opens it correctly)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "leads": {"type": "array", "items": {"type": "object"},
                          "description": "The `leads` array returned by find_businesses_without_website."},
                "path": {"type": "string", "default": "local-leads.csv",
                         "description": "Destination CSV path."},
            },
            "required": ["leads"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 sobre stdio
# ---------------------------------------------------------------------------
def enviar(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(rid, result: dict) -> None:
    enviar({"jsonrpc": "2.0", "id": rid, "result": result})


def error(rid, code: int, message: str) -> None:
    enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def manejar(msg: dict) -> None:
    metodo = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    if metodo == "initialize":
        pedido = params.get("protocolVersion")
        ok(rid, {
            "protocolVersion": pedido if pedido in PROTOCOL_SUPPORTED else PROTOCOL_DEFAULT,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif metodo in ("notifications/initialized", "initialized"):
        return  # notificacion: sin respuesta
    elif metodo == "ping":
        ok(rid, {})
    elif metodo == "tools/list":
        ok(rid, {"tools": TOOLS})
    elif metodo == "tools/call":
        nombre = params.get("name")
        args = params.get("arguments") or {}
        try:
            if nombre == "find_businesses_without_website":
                resultado = tool_find(args)
            elif nombre == "export_leads_csv":
                resultado = tool_export_csv(args)
            else:
                error(rid, -32602, f"Herramienta desconocida: {nombre}")
                return
        except PlacesError as e:
            # Un fallo del servicio externo es un resultado de la herramienta, no un
            # error de protocolo: el cliente de IA puede leerlo, explicarlo y reintentar.
            ok(rid, {"content": [{"type": "text", "text": json.dumps(
                {"error": str(e)}, ensure_ascii=False, indent=2)}], "isError": True})
            return
        texto = json.dumps(resultado, ensure_ascii=False, indent=2)
        ok(rid, {
            "content": [{"type": "text", "text": texto}],
            "isError": "error" in resultado,
        })
    elif rid is not None:
        error(rid, -32601, f"Metodo no soportado: {metodo}")


def main() -> int:
    log(f"{SERVER_NAME} {SERVER_VERSION} listo (stdio)")
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except json.JSONDecodeError:
            error(None, -32700, "JSON invalido")
            continue
        if not isinstance(msg, dict):
            error(None, -32600, "Se esperaba un objeto JSON-RPC")
            continue
        try:
            manejar(msg)
        except PlacesError as e:
            error(msg.get("id"), -32000, str(e))
        except Exception as e:  # nunca tumbar el servidor por una peticion
            log(f"error inesperado: {e!r}")
            error(msg.get("id"), -32603, f"Error interno: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
