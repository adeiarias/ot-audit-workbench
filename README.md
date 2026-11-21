# Audit Platform

Plataforma local para gestionar campañas de auditoría de seguridad. Ver el plan en `~/.claude/plans/`.

## Desarrollo
```bash
# Backend (http://127.0.0.1:8000)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --reload
.venv/bin/python -m pytest

# Frontend (http://127.0.0.1:5173, proxy /api -> :8000)
cd frontend && npm install && npm run dev
```
Los datos se guardan en `data/` (SQLite + ficheros), fuera de git.

## Capturas y mapa
- Pestaña **Capturas**: sube `.pcap`/`.pcapng` (hay uno de ejemplo en `samples/demo_ot.pcap`). Se analiza offline con tshark.
- Pestaña **Mapa**: grafo lógico (activos y flujos por protocolo/puerto). Se actualiza en vivo por WebSocket.
- Los hosts fuera del alcance aparecen en el mapa (gris) pero no se crean como activos.
- **Contenido de protocolo**: además de ver qué protocolo se usa, se decodifica lo que se envió en HTTP (método, URL, host), MQTT (CONNECT, topics y una muestra del payload), Modbus/TCP (función, dirección, valores de lecturas y escrituras), S7comm (lectura/escritura de variables, parada de CPU) y FTP (comandos y ficheros). En la pestaña **Mapa**, pulsa un flujo de la tabla para ver su contenido. Las operaciones que modifican estado (escritura/control) se resaltan.
- **Credenciales en claro** (HTTP Basic, `Authorization`, MQTT CONNECT, FTP USER/PASS) se muestran tal cual y se marcan con ⚠: son posibles hallazgos. No se envían al asistente de IA.
- Limitaciones: solo se interpretan los puertos estándar (80, 1883, 502, 102, 21); no se reensamblan los cuerpos HTTP ni los canales de datos FTP; los eventos se agrupan por flujo y resumen (un máximo de 300 distintos por flujo).

## MCPs de terceros
- Se declaran en `backend/mcp_servers.yaml` (hay un ejemplo con [Wireshark-MCP](https://github.com/bx33661/Wireshark-MCP), instalado y fijado en la imagen Docker). **Solo existen las herramientas que listes**: el resto se deniega.
- Por herramienta: `active`, `allowed_args` (lista cerrada: rutas de salida, `sudo` o flags crudos se rechazan), y `target_arg` (se valida contra el alcance) o `capture_arg` (indicas el ID de una captura y la app resuelve la ruta, siempre dentro de la campaña). Con `llm: false` solo el auditor puede usarla (no el asistente).
- El servidor arranca con un entorno mínimo: no ve tus claves. Fuera de Docker, si el ejecutable no existe, el servidor se omite con un aviso.
- Las herramientas pasivas sobre capturas aparecen en **Herramientas** y el asistente las usa sin aprobación (son offline); las activas siempre la piden.

## Variables de entorno
- `AUDIT_MCP_MANIFEST`: ruta de otro manifiesto de MCPs de terceros.
- `AUDIT_DATA_DIR`: carpeta de datos (por defecto `./data`). Úsala para pruebas aisladas.
- `AUDIT_ALLOWED_ORIGINS` / `AUDIT_ALLOWED_HOSTS`: orígenes y hosts aceptados por la API
  (por defecto solo `127.0.0.1`/`localhost` y el Vite en `:5173`).

## Hallazgos y evidencias
- **Hallazgos**: estructura del informe (Identifier, Name, Criticality, Affected assets, Description/PoC/Impact, Recommendations), agrupados por fase. El vector y la puntuación CVSS los introduces tú; la criticidad (Low/Medium/High/Critical) se deriva de la puntuación.
- **Evidencias**: imágenes PNG/JPEG/GIF/WebP (arrastrar, pegar con Ctrl+V o seleccionar). En el editor de un hallazgo, los botones «Insertar Evidencia N» añaden `[Evidencia N: descripción]` al PoC.
- `API_TARGET`: destino del proxy de Vite (por defecto `http://127.0.0.1:8000`), útil para probar contra otro backend.

## Asistente (LLM) — Fase 4
- Pestaña **Asistente**: chat por campaña con el contexto de la auditoría. Modelo por defecto `claude-opus-5-5` (`AUDIT_LLM_MODEL`, `AUDIT_LLM_EFFORT`).
- Requiere `ANTHROPIC_API_KEY` en el entorno del backend (o un perfil de `ant auth login`). **Lo que lee el asistente se envía a la API de Anthropic.**
- Por campaña: «Permitir LLM» (apagado por defecto) y «Anonimizar» (encendido por defecto: IPs, CIDR, MAC y hostnames → `IP-0001`…; secretos → `[REDACTED]`).
- Las herramientas activas (nmap, modbus) **nunca** se ejecutan sin tu aprobación, y el objetivo se valida contra el alcance al proponerlas y al aprobarlas.

## Informes — Fase 5
- Pestaña **Informe**: metadatos y textos; descarga en **Word**, **PDF** y **Markdown**. «✨ Borrador con IA» para los resúmenes y conclusiones (nunca se guarda solo).
- El Word usa Arial, negro para el texto y cian solo como acento, sin logotipo. La maquetación vive solo en `backend/app/report/docx_builder.py`.
- El PDF necesita LibreOffice (`soffice`) y el `python3` del sistema con el módulo `uno`.
- Word actualiza el índice al abrir (te preguntará si actualizar los campos: di que sí).
- Al arrancar tras actualizar, el backend añade columnas nuevas a tu BD y hace antes una copia `audit.db.bak-<fecha>` junto al fichero.

## Proveedores de LLM (Claude, DeepSeek, LiteLLM, cualquier API compatible con OpenAI)
Se elige por variables de entorno del backend (reinícialo tras cambiarlas):

| Variable | Qué hace |
|---|---|
| `AUDIT_LLM_PROVIDER` | `anthropic` (por defecto), `deepseek`, `litellm` u `openai` (cualquier `/chat/completions`: Ollama, vLLM, OpenAI…) |
| `AUDIT_LLM_MODEL` | Modelo. Por defecto `claude-opus-5-5` / `deepseek-flash`. En LiteLLM, el `model_name` de tu `config.yaml` |
| `AUDIT_LLM_BASE_URL` | DeepSeek: `https://api.deepseek.com` · LiteLLM: `http://localhost:4000` · `openai`: obligatoria (p. ej. `http://localhost:11434/v1`) |
| `AUDIT_LLM_API_KEY` | O la propia: `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `LITELLM_API_KEY`, `OPENAI_API_KEY` (opcional si el servidor no la exige) |
| `AUDIT_LLM_EFFORT` | Esfuerzo de razonamiento (`low`…`max`) para Claude y DeepSeek. Por defecto `high` |
| `AUDIT_LLM_MAX_TOKENS` | Salida máxima en proveedores OpenAI-compatibles (8192) |
| `AUDIT_LLM_TOOLS` | `0` para modelos sin soporte de herramientas: el chat solo ve la instantánea inicial |
| `AUDIT_LLM_PASS_REASONING` | Reenviar `reasoning_content` (por defecto solo en `deepseek`; actívalo si LiteLLM apunta a DeepSeek) |
| `AUDIT_LLM_EXTRA_BODY` | JSON que se fusiona en la petición, p. ej. `{"thinking":{"type":"disabled"}}` |

Ejemplos:
```bash
# DeepSeek
AUDIT_LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=sk-... uvicorn app.main:app --host 127.0.0.1
# LiteLLM (proxy local que puede apuntar a un modelo local con Ollama)
AUDIT_LLM_PROVIDER=litellm AUDIT_LLM_MODEL=mi-alias uvicorn app.main:app --host 127.0.0.1
```
- La interfaz muestra proveedor, modelo y si el servidor es **externo** o **local** (localhost / red privada), y lo cita al habilitar el LLM en una campaña.
- La anonimización, la aprobación humana y el control de alcance son idénticos con cualquier proveedor.
- Una conversación no se mezcla entre proveedores: si cambias de proveedor, pulsa «Nueva conversación».


## Interfaz (rediseño)
- Barra lateral colapsable con las campañas y, dentro de una campaña, sus secciones (Resumen, Herramientas, Activos, Capturas, Mapa, Hallazgos, Evidencias, Asistente, Informe). Cada sección tiene su URL (`/campaigns/3/findings`).
- **Resumen** de cada campaña: tarjetas y gráficos (hallazgos por criticidad, protocolos), alcance, actividad reciente y estado del asistente y del informe.
- **Temas**: claro/oscuro/sistema y 5 presets (Audit, Neutro, Soft Pop, Tangerine, Brutalist; los cuatro últimos adaptados de «Studio Admin», MIT). Menú del sol/luna en la cabecera o en Ajustes.
- Stack: React + Vite 5 + **Tailwind 3.4** (Tailwind 4 exige Node 20+) + componentes estilo shadcn/ui en `frontend/src/components/ui`.

## Alcance editable
- «Editar alcance» (cabecera de la campaña y Resumen): análisis en vivo con errores **por línea**, aviso de rangos enormes (`0.0.0.0/0`), vista previa de lo añadido/quitado e **historial** de cambios (también el alcance inicial).
- Al quitar entradas: los activos ya descubiertos se conservan pero se marcan «fuera de alcance», y las acciones del asistente pendientes de aprobar cuyo objetivo quede fuera se rechazan solas.

## Perfiles de IA (Ajustes → Proveedores de IA)
- Crea perfiles para Anthropic, DeepSeek, LiteLLM u OpenAI-compatible (URL, modelo, clave, esfuerzo…) y pruébalos con «Probar» (un `ping`, sin datos de campañas).
- Cada campaña elige el suyo en la pestaña **Asistente**; sin elección usa el perfil predeterminado y, si no hay, la configuración por entorno (`AUDIT_LLM_*`).
- **Las claves se guardan en texto plano en `audit.db`** (permisos 600; también sus copias de seguridad). La API nunca las devuelve; la interfaz solo muestra los 4 últimos caracteres.
- Cambiar de proveedor en una campaña con conversación abierta exige «Nueva conversación».
