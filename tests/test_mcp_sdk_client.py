#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interoperabilidad con el cliente OFICIAL de MCP (SDK `mcp` de Python).

Si el SDK esta instalado, arranca `server.py` con `stdio_client` + `ClientSession`
(el mismo camino que usan Claude Desktop y Claude Code) contra un mock de Places y
comprueba initialize / list_tools / call_tool. Si el SDK no esta, termina en 0 con
un aviso (no es un fallo del servidor).

    python3 product/scripts/test_mcp_sdk_client.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
SERVER = next((p for p in (RAIZ / "server.py", RAIZ / "mcp-local-leads" / "server.py") if p.exists()),
              RAIZ / "server.py")
sys.path.insert(0, str(SCRIPTS))

try:
    from mcp import ClientSession, StdioServerParameters  # noqa: E402
    from mcp.client.stdio import stdio_client          # noqa: E402
    SDK = True
except Exception as e:                                  # pragma: no cover
    print(f"SDK mcp no disponible ({e}); se omite esta prueba.")
    raise SystemExit(0)

from test_mcp_local_leads import Mock                   # noqa: E402

fallos = 0


def check(cond, msg):
    global fallos
    if cond:
        print(f"  OK    {msg}")
    else:
        fallos += 1
        print(f"  FALLA {msg}")


async def correr(puerto: int, tmp: Path) -> None:
    env = dict(os.environ)
    env["GOOGLE_PLACES_API_KEY"] = "clave-de-prueba"
    env["PLACES_BASE_URL"] = f"http://127.0.0.1:{puerto}"
    env["PLACES_TIMEOUT"] = "10"
    env.pop("PYTHONPATH", None)
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            check(info.server_info.name == "mcp-local-leads",
                  f"initialize con el SDK oficial -> {info.server_info.name} {info.server_info.version}")

            tools = await session.list_tools()
            nombres = [t.name for t in tools.tools]
            check(len(nombres) == 2, f"list_tools devuelve {nombres}")
            check("find_businesses_without_website" in nombres, "el SDK ve la herramienta de busqueda")

            res = await session.call_tool("find_businesses_without_website",
                                          {"city": "Temuco, Chile", "niche": "dental clinics", "limit": 10})
            check(res.is_error is False, "call_tool sin error")
            datos = json.loads(res.content[0].text)
            check(datos["without_website"] == 4,
                  f"leads sin web por el SDK oficial = {datos['without_website']}")
            check([l["place_id"] for l in datos["leads"]] == ["p1", "p3", "p5", "p7"],
                  "mismos ids que en la prueba directa")

            res2 = await session.call_tool("export_leads_csv",
                                           {"leads": datos["leads"], "path": str(tmp / "sdk.csv")})
            check(res2.is_error is False and (tmp / "sdk.csv").exists(), "export_leads_csv por el SDK")


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp(prefix="mcp-sdk-"))
    print(f"== Cliente oficial de MCP contra el mock en 127.0.0.1:{puerto} ==")
    asyncio.run(correr(puerto, tmp))
    srv.shutdown()
    print("RESULTADO:", "FALLA" if fallos else "TODO OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
