#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba real del servidor MCP **dentro de Docker** (lo que Glama ejecuta).

Glama (y cualquier directorio que valide servidores) construye la imagen del
repositorio y comprueba que el servidor **arranca y responde a la
introspeccion** (initialize + tools/list). Esta prueba hace exactamente eso en
esta maquina, contra la misma imagen que se publica:

  1. docker build de `product/mcp-local-leads`
  2. docker run -i (stdio, sin TTY) con un mock de Places API (New) en el host
  3. initialize -> tools/list -> tools/call -> export_leads_csv
  4. arranque sin GOOGLE_PLACES_API_KEY: debe responder con isError nombrando la variable

Sale con codigo 1 si cualquier fase falla (una prueba que no falla no prueba nada).

    python3 product/scripts/test_mcp_docker.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Sirve en el workspace (product/mcp-local-leads/) y en el repositorio publicado
# (Dockerfile en la raiz): se prueba exactamente lo que se publica.
CTX = next((p for p in (RAIZ / "mcp-local-leads", RAIZ) if (p / "Dockerfile").exists()),
           RAIZ / "mcp-local-leads")
IMAGEN = "mcp-local-leads:test"

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


PAGINA_1 = {
    "places": [
        {"id": "p1", "displayName": {"text": "Dental Norte"},
         "formattedAddress": "Av. Alemania 123, Temuco, La Araucanía, Chile",
         "nationalPhoneNumber": "+56 45 123 4567", "rating": 4.6, "userRatingCount": 88,
         "primaryTypeDisplayName": {"text": "Dental clinic"}},
        {"id": "p2", "displayName": {"text": "Clinica Sonrisa"},
         "formattedAddress": "Av. Alemania 800, Temuco, La Araucanía, Chile",
         "websiteUri": "https://sonrisa.cl", "rating": 4.2},
        {"id": "p3", "displayName": {"text": "Dental Sur"},
         "formattedAddress": "Calle Sur 45, Temuco, La Araucanía, Chile"},
    ],
}


class Mock(BaseHTTPRequestHandler):
    pedidos: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        Mock.pedidos.append({"mask": self.headers.get("X-Goog-FieldMask"),
                             "key": self.headers.get("X-Goog-Api-Key")})
        out = json.dumps(PAGINA_1).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class Contenedor:
    """Cliente MCP por stdio contra `docker run -i`."""

    def __init__(self, base_url: str | None, con_clave: bool = True):
        args = ["docker", "run", "-i", "--rm", "--network", "host",
                "--name", f"mcp-leads-test-{os.getpid()}-{int(time.time())}"]
        if con_clave:
            args += ["-e", "GOOGLE_PLACES_API_KEY=clave-de-prueba"]
        if base_url:
            args += ["-e", f"PLACES_BASE_URL={base_url}", "-e", "PLACES_TIMEOUT=10"]
        args.append(IMAGEN)
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self._n = 0

    def pedir(self, metodo: str, params: dict | None = None) -> dict:
        self._n += 1
        msg = {"jsonrpc": "2.0", "id": self._n, "method": metodo}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        linea = self.p.stdout.readline()
        if not linea:
            err = self.p.stderr.read()[:800]
            raise SystemExit(f"el contenedor no respondio: {err}")
        return json.loads(linea)

    def notificar(self, metodo: str) -> None:
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": metodo}) + "\n")
        self.p.stdin.flush()

    def llamar(self, nombre: str, args: dict):
        r = self.pedir("tools/call", {"name": nombre, "arguments": args})
        res = r.get("result") or {}
        texto = (res.get("content") or [{}])[0].get("text", "{}")
        return res, json.loads(texto)

    def cerrar(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=15)
        except Exception:
            self.p.kill()


def main() -> int:
    if not (CTX / "Dockerfile").exists():
        print("ERROR: falta", CTX / "Dockerfile")
        return 1

    print("1) docker build")
    t0 = time.time()
    r = subprocess.run(["docker", "build", "-t", IMAGEN, str(CTX)],
                       capture_output=True, text=True)
    print("   " + (r.stdout.strip().splitlines() or [""])[-1])
    check(r.returncode == 0, f"la imagen se construyo ({time.time()-t0:.1f}s)")
    if r.returncode != 0:
        print(r.stderr[-2000:])
        print(f"\nRESULTADO: FALLOS ({fallos})")
        return 1

    print("\n2) arranque sin clave (debe informar, no romper el protocolo)")
    c = Contenedor(base_url=None, con_clave=False)
    r = c.pedir("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "docker-test", "version": "1"}})
    info = (r.get("result") or {}).get("serverInfo") or {}
    check(info.get("name") == "mcp-local-leads", f"serverInfo.name = {info.get('name')}")
    c.notificar("notifications/initialized")
    res, datos = c.llamar("find_businesses_without_website", {"city": "Temuco, Chile"})
    check(res.get("isError") is True, "sin clave la herramienta responde isError=true")
    check("GOOGLE_PLACES_API_KEY" in json.dumps(datos), "el mensaje nombra GOOGLE_PLACES_API_KEY")
    c.cerrar()

    print("\n3) mock de Places en el host + busqueda real dentro del contenedor")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"   mock en 127.0.0.1:{puerto}")

    c = Contenedor(base_url=f"http://127.0.0.1:{puerto}")
    r = c.pedir("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "docker-test", "version": "1"}})
    check((r.get("result") or {}).get("protocolVersion") == "2025-06-18", "negocia protocolo")
    c.notificar("notifications/initialized")
    r = c.pedir("tools/list", {})
    tools = (r.get("result") or {}).get("tools") or []
    check(len(tools) == 2, f"tools/list devuelve 2 herramientas ({len(tools)})")

    Mock.pedidos.clear()
    res, datos = c.llamar("find_businesses_without_website",
                          {"city": "Temuco, Chile", "niche": "dental clinics", "limit": 10})
    check(res.get("isError") is False, "la llamada no marca error")
    check(datos.get("businesses_seen") == 3, f"negocios vistos = 3 ({datos.get('businesses_seen')})")
    check(datos.get("without_website") == 2, f"sin web = 2 ({datos.get('without_website')})")
    ids = [l["place_id"] for l in datos.get("leads", [])]
    check(ids == ["p1", "p3"], f"ids sin web = {ids}")
    check(len(Mock.pedidos) == 1, f"el mock recibio 1 POST ({len(Mock.pedidos)})")
    mask = (Mock.pedidos[0]["mask"] if Mock.pedidos else "") or ""
    check(len([m for m in mask.split(",") if m.startswith("places.")]) == 11,
          "field mask de 11 campos (Places factura por campo)")
    check(Mock.pedidos[0]["key"] == "clave-de-prueba", "la clave viaja en X-Goog-Api-Key")

    print("\n4) export_leads_csv dentro del contenedor")
    res, datos = c.llamar("export_leads_csv",
                          {"path": "/tmp/leads.csv", "leads": datos.get("leads") or []})
    check(res.get("isError") is False, "export responde sin error")
    check(datos.get("rows") == 2, f"filas escritas = 2 ({datos.get('rows')})")
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", IMAGEN,
                        "-c", "print('ok')"], capture_output=True, text=True)
    check(r.returncode == 0, "la imagen arranca python3 (entrypoint sano)")

    c.cerrar()
    srv.shutdown()

    print()
    if fallos:
        print(f"RESULTADO: FALLOS ({fallos} de {checks})")
        return 1
    print(f"RESULTADO: TODO OK ({checks} comprobaciones, imagen {IMAGEN})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
