# mcp-local-leads — imagen minima.
#
# El servidor usa SOLO la libreria estandar de Python: no hay `pip install`,
# ni node, ni dependencias que puedan romperse con el tiempo. La imagen pesa
# poco mas que el propio interprete y arranca en JSON-RPC over stdio.
#
#   docker build -t mcp-local-leads .
#   docker run -i --rm -e GOOGLE_PLACES_API_KEY=tu_clave mcp-local-leads
#
# Los clientes MCP lanzan el servidor y hablan por stdin/stdout, asi que el
# contenedor se usa con -i (stdin abierto) y sin -t (nada de pseudo-TTY, que
# ensuciaria el protocolo).
#
# La etiqueta `io.modelcontextprotocol.server.name` es el requisito del registro
# oficial de MCP (registry.modelcontextprotocol.io): es como ese registro
# comprueba que quien publica la imagen controla ese nombre de servidor. Debe
# coincidir EXACTAMENTE con el `name` de `server.json`.

FROM python:3.12-slim

LABEL io.modelcontextprotocol.server.name="io.github.ellokillox/mcp-local-leads"
LABEL org.opencontainers.image.title="mcp-local-leads" \
      org.opencontainers.image.description="MCP server: find local businesses without a website (Google Places API New)." \
      org.opencontainers.image.url="https://b2b.medicpc51.cl/mcp-server/" \
      org.opencontainers.image.source="https://github.com/ellokillox/mcp-local-leads" \
      org.opencontainers.image.licenses="MIT"

# Sin bytecode y sin buffer: una linea JSON por mensaje, sin retencion.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# Un solo archivo: es todo el servidor.
COPY server.py /app/server.py

# Usuario sin privilegios: el servidor solo necesita hacer HTTP saliente.
RUN useradd --create-home --uid 10001 mcp \
    && chown -R mcp:mcp /app
USER mcp

# Sin argumentos: el protocolo ya es stdio.
ENTRYPOINT ["python3", "/app/server.py"]
