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

FROM python:3.12-slim

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
