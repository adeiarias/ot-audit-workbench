FROM python:3.12-slim-trixie

# nmap y tshark los usan los servidores MCP. LibreOffice (+ python3-uno del sistema) solo hace falta para exportar a PDF:
#   docker compose build --build-arg WITH_PDF=0   para una imagen mucho más ligera, sin PDF.
ARG WITH_PDF=1
ARG UID=1000
ARG GID=1000
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nmap tshark \
 && if [ "$WITH_PDF" = "1" ]; then \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libreoffice-writer python3-uno poppler-utils fonts-liberation; \
    fi \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g "$GID" audit && useradd -m -u "$UID" -g "$GID" audit

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# MCP de terceros: venv propio (sus dependencias no se mezclan con las de la app) y versión fijada. Se declaran en mcp_servers.yaml.
RUN python -m venv /opt/mcp/wireshark && /opt/mcp/wireshark/bin/pip install --no-cache-dir wireshark-mcp==4.0.0

COPY app ./app
COPY mcp_servers ./mcp_servers
COPY mcp_servers.yaml ./mcp_servers.yaml
COPY scripts ./scripts

ENV AUDIT_DATA_DIR=/data PYTHONUNBUFFERED=1
USER audit
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
