#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba real de `product/mcp-local-leads/server.py`.

Levanta un mock HTTP de Places API (New) en 127.0.0.1 (puerto efimero), arranca el
servidor MCP como subproceso y le habla JSON-RPC 2.0 por stdio, igual que Claude
Desktop. No usa la API real ni necesita clave.

    python3 product/scripts/test_mcp_local_leads.py

Sale con codigo 1 si cualquier comprobacion falla.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# El mismo archivo sirve en el workspace (product/mcp-local-leads/server.py) y en el
# repositorio publicado (server.py en la raiz): se publica exactamente lo que se probo.
SERVER = next((p for p in (RAIZ / "server.py", RAIZ / "mcp-local-leads" / "server.py") if p.exists()),
              RAIZ / "server.py")

fallos = 0
checks = 0


def check(cond, msg):
    global fallos, checks
    checks += 1
    if cond:
        print(f"  OK    {msg}")
    else:
        fallos += 1
        print(f"  FALLA {msg}")


# ---------------------------------------------------------------------------
# Mock de Places API (New)
# ---------------------------------------------------------------------------
PAGINA_1 = {
    "places": [
        {"id": "p1", "displayName": {"text": "Dental Norte"}, "formattedAddress":
            "Av. Alemania 123, Temuco, La Araucanía, Chile", "nationalPhoneNumber": "+56 45 123 4567",
         "rating": 4.6, "userRatingCount": 88, "googleMapsUri": "https://maps.google.com/?cid=1",
         "primaryTypeDisplayName": {"text": "Dental clinic"}, "businessStatus": "OPERATIONAL",
         "location": {"latitude": -38.7359, "longitude": -72.5904}},
        {"id": "p2", "displayName": {"text": "Clinica Sonrisa"}, "formattedAddress":
            "Av. Alemania 800, Temuco, La Araucanía, Chile", "websiteUri": "https://sonrisa.cl",
         "rating": 4.2, "userRatingCount": 30, "location": {"latitude": -38.74, "longitude": -72.6}},
        {"id": "p3", "displayName": {"text": "Dental Sur"}, "formattedAddress":
            "Calle Sur 45, Temuco, La Araucanía, Chile",
         "location": {"latitude": -38.75, "longitude": -72.61}},
        {"id": "p4", "displayName": {"text": "Odonto Express"}, "formattedAddress":
            "Calle Sur 99, Temuco, La Araucanía, Chile", "websiteUri": "http://odontoexpress.cl",
         "rating": 3.9, "userRatingCount": 12, "location": {"latitude": -38.76, "longitude": -72.62}},
    ],
    "nextPageToken": "T2",
}
PAGINA_2 = {
    "places": [
        # p1 repetido a proposito: el servidor debe descartarlo
        {"id": "p1", "displayName": {"text": "Dental Norte"}, "formattedAddress":
            "Av. Alemania 123, Temuco, La Araucanía, Chile"},
        {"id": "p5", "displayName": {"text": "Dental Centro"}, "formattedAddress":
            "Centro 12, Temuco, La Araucanía, Chile", "nationalPhoneNumber": "+56 45 999 8888",
         "rating": 4.9, "userRatingCount": 210, "location": {"latitude": -38.73, "longitude": -72.58}},
        {"id": "p6", "displayName": {"text": "Clinica Web"}, "formattedAddress":
            "Centro 55, Temuco, La Araucanía, Chile", "websiteUri": "https://clinicaweb.cl"},
        {"id": "p7", "displayName": {"text": "Dental Poniente"}, "formattedAddress":
            "Poniente 7, Temuco, La Araucanía, Chile", "location": {"latitude": -38.72, "longitude": -72.65}},
    ],
}


class Mock(BaseHTTPRequestHandler):
    pedidos: list = []
    modo_error = {"on": False}

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        Mock.pedidos.append({"path": self.path, "body": cuerpo,
                             "mask": self.headers.get("X-Goog-FieldMask"),
                             "key": self.headers.get("X-Goog-Api-Key")})
        if Mock.modo_error["on"]:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"code":400,"message":"API key not valid"}}')
            return
        token = cuerpo.get("pageToken")
        data = PAGINA_2 if token == "T2" else PAGINA_1
        if token == "T3":
            data = {"places": []}
        out = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):  # silencio
        pass


# ---------------------------------------------------------------------------
# Cliente MCP minimo
# ---------------------------------------------------------------------------
class Cliente:
    def __init__(self, data_dir: Path, con_clave: bool = True):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        if con_clave:
            env["GOOGLE_PLACES_API_KEY"] = "clave-de-prueba"
        else:
            env.pop("GOOGLE_PLACES_API_KEY", None)
        env["PLACES_TIMEOUT"] = "10"
        self.p = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1, env=env)
        self.raw: list[str] = []
        self._n = 0

    def pedir(self, metodo: str, params: dict | None = None) -> dict:
        self._n += 1
        msg = {"jsonrpc": "2.0", "id": self._n, "method": metodo}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        linea = self.p.stdout.readline()
        self.raw.append(linea)
        return json.loads(linea)

    def notificar(self, metodo: str) -> None:
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": metodo}) + "\n")
        self.p.stdin.flush()

    def llamar(self, nombre: str, args: dict) -> tuple[dict, dict]:
        r = self.pedir("tools/call", {"name": nombre, "arguments": args})
        res = r.get("result") or {}
        texto = (res.get("content") or [{}])[0].get("text", "{}")
        return res, json.loads(texto)

    def cerrar(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def main() -> int:
    if not SERVER.exists():
        print("ERROR: no existe", SERVER)
        return 1

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["PLACES_BASE_URL"] = f"http://127.0.0.1:{puerto}"
    print(f"== Mock de Places escuchando en 127.0.0.1:{puerto} ==\n")

    tmp = Path(tempfile.mkdtemp(prefix="mcp-leads-test-"))

    print("1) Handshake MCP")
    c = Cliente(tmp)
    r = c.pedir("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "test", "version": "1"}})
    info = (r.get("result") or {}).get("serverInfo") or {}
    check(r.get("jsonrpc") == "2.0" and r.get("id") == 1, "responde JSON-RPC con el mismo id")
    check(info.get("name") == "mcp-local-leads", f"serverInfo.name = {info.get('name')}")
    check((r.get("result") or {}).get("protocolVersion") == "2025-06-18", "negocia la version de protocolo")
    c.notificar("notifications/initialized")

    print("\n2) tools/list")
    r = c.pedir("tools/list", {})
    tools = (r.get("result") or {}).get("tools") or []
    nombres = [t["name"] for t in tools]
    check(len(tools) == 2, f"2 herramientas ({len(tools)})")
    check("find_businesses_without_website" in nombres, "existe find_businesses_without_website")
    check("export_leads_csv" in nombres, "existe export_leads_csv")
    find = [t for t in tools if t["name"] == "find_businesses_without_website"][0]
    check(find["inputSchema"].get("required") == ["city"], "`city` es el unico parametro obligatorio")
    check("limit" in find["inputSchema"]["properties"], "declara `limit`")

    print("\n3) Busqueda real contra el mock (2 paginas)")
    Mock.pedidos.clear()
    res, datos = c.llamar("find_businesses_without_website",
                          {"city": "Temuco, Chile", "niche": "dental clinics", "limit": 10})
    check(res.get("isError") is False, "la llamada no marca error")
    check(datos.get("businesses_seen") == 7, f"negocios vistos = 7 ({datos.get('businesses_seen')})")
    check(datos.get("with_website") == 3, f"con web = 3 ({datos.get('with_website')})")
    check(datos.get("without_website") == 4, f"sin web = 4 ({datos.get('without_website')})")
    ids = [l["place_id"] for l in datos["leads"]]
    check(ids == ["p1", "p3", "p5", "p7"], f"ids sin web y sin duplicados: {ids}")
    check(datos.get("pages") == 2 and datos.get("requests") == 2, "leyo 2 paginas (2 peticiones)")
    check(len(Mock.pedidos) == 2, f"el mock recibio 2 POST ({len(Mock.pedidos)})")
    check(Mock.pedidos[0]["path"] == "/v1/places:searchText", "ruta correcta de Text Search (New)")
    check(Mock.pedidos[0]["body"].get("textQuery") == "dental clinics in Temuco, Chile",
          f"textQuery = {Mock.pedidos[0]['body'].get('textQuery')}")
    check(Mock.pedidos[0]["body"].get("pageSize") == 20, "pageSize por defecto 20")
    check(Mock.pedidos[1]["body"].get("pageToken") == "T2", "la 2a peticion envia pageToken")
    mask = Mock.pedidos[0]["mask"] or ""
    check("places.websiteUri" in mask and "nextPageToken" in mask, "field mask incluye websiteUri y nextPageToken")
    check(len([m for m in mask.split(",") if m.startswith("places.")]) == 11,
          f"field mask estrecha: 11 campos ({len([m for m in mask.split(',') if m.startswith('places.')])})")
    check(Mock.pedidos[0]["key"] == "clave-de-prueba", "envia la clave en X-Goog-Api-Key")
    lead1 = datos["leads"][0]
    check(lead1["ciudad"] == "La Araucanía",
          f"ciudad = penultima parte de la direccion ({lead1['ciudad']!r}, no 'Chile')")
    check(lead1["telefono"] == "+56 45 123 4567", "conserva el telefono")
    check(lead1["rating"] == 4.6 and lead1["resenas"] == 88, "conserva rating y resenas")
    check("has_website" not in lead1, "no devuelve el campo interno has_website")

    print("\n4) `limit` se respeta y corta la paginacion")
    Mock.pedidos.clear()
    _, d2 = c.llamar("find_businesses_without_website", {"city": "Temuco", "niche": "dental", "limit": 2})
    check(len(d2["leads"]) == 2, f"devuelve 2 ({len(d2['leads'])})")
    check(d2.get("pages") == 1, f"corta en 1 pagina al alcanzar el limite ({d2.get('pages')})")

    print("\n5) max_pages=1 no pide la segunda pagina")
    Mock.pedidos.clear()
    _, d3 = c.llamar("find_businesses_without_website",
                     {"city": "Temuco", "niche": "dental", "limit": 50, "max_pages": 1})
    check(d3.get("pages") == 1 and len(Mock.pedidos) == 1, "una sola peticion")
    check(d3.get("next_page_token") == "T2", "devuelve el next_page_token para continuar")

    print("\n6) Exportacion a CSV")
    destino = tmp / "sub" / "leads-temuco.csv"
    _, exp = c.llamar("export_leads_csv", {"leads": datos["leads"], "path": str(destino)})
    check(Path(exp.get("path", "")).exists(), "el archivo existe")
    with open(exp["path"], encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    check(len(filas) == 4, f"4 filas ({len(filas)})")
    check(list(filas[0].keys())[:4] == ["place_id", "nombre", "direccion", "ciudad"],
          f"columnas: {list(filas[0].keys())[:4]}")
    check(filas[0]["nombre"] == "Dental Norte", "conserva el nombre en el CSV")
    check(exp.get("rows") == 4, "informa las filas escritas")

    print("\n7) Error de Places (HTTP 400) se informa sin matar el servidor")
    Mock.modo_error["on"] = True
    res, err = c.llamar("find_businesses_without_website", {"city": "Temuco"})
    check(res.get("isError") is True, "marca isError")
    check("400" in json.dumps(err), f"el mensaje menciona el HTTP 400: {str(err)[:90]}")
    Mock.modo_error["on"] = False
    res, ok2 = c.llamar("find_businesses_without_website", {"city": "Temuco", "limit": 1})
    check(res.get("isError") is False and ok2["leads"], "sigue vivo y responde despues del error")

    print("\n8) Parametros invalidos")
    res, err = c.llamar("find_businesses_without_website", {})
    check(res.get("isError") is True and "city" in json.dumps(err), "exige `city`")
    res, err = c.llamar("export_leads_csv", {})
    check(res.get("isError") is True, "export sin `leads` falla con mensaje")
    r = c.pedir("tools/call", {"name": "no_existe", "arguments": {}})
    check((r.get("error") or {}).get("code") == -32602, "herramienta desconocida -> error JSON-RPC -32602")

    print("\n9) Sin GOOGLE_PLACES_API_KEY")
    c2 = Cliente(tmp, con_clave=False)
    c2.pedir("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    res, err = c2.llamar("find_businesses_without_website", {"city": "Temuco"})
    check(res.get("isError") is True, "falla con mensaje")
    check("GOOGLE_PLACES_API_KEY" in json.dumps(err), "el mensaje nombra la variable que falta")
    c2.cerrar()

    print("\n10) stdout solo JSON-RPC")
    c.cerrar()
    lineas_ok = 0
    for linea in c.raw:
        if not linea.strip():
            continue
        try:
            json.loads(linea)
            lineas_ok += 1
        except json.JSONDecodeError:
            check(False, f"linea no-JSON en stdout: {linea[:80]!r}")
    check(lineas_ok == len(c.raw), f"{lineas_ok}/{len(c.raw)} lineas de stdout son JSON")
    err_out = c.p.stderr.read() if c.p.stderr else ""
    check("[mcp-local-leads]" in err_out or err_out == "", "los logs van a stderr")

    srv.shutdown()
    print(f"\n== {checks} comprobaciones · {fallos} fallos ==")
    if fallos:
        print("RESULTADO: FALLA")
        return 1
    print("RESULTADO: TODO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
