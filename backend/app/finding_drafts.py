"""Borradores de hallazgo a partir de eventos de protocolo vistos en una captura (credenciales en claro, escrituras, órdenes de control).

Plantillas deterministas (sin LLM): el hallazgo nace en borrador, sin identificador ni CVSS, para que el auditor los complete.
Las contraseñas se enmascaran en el texto del informe (el valor completo sigue en la captura).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Asset, Capture, FlowEvent

LABEL = {"http": "HTTP", "mqtt": "MQTT", "modbus": "Modbus/TCP", "s7": "S7comm", "ftp": "FTP"}
NO_AUTH = {"modbus", "s7"}  # protocolos sin autenticación nativa (S7comm clásico, Modbus/TCP)
DRAFTABLE_KINDS = ("auth", "control", "write")

_TLS_FIX = {
    "http": "Servir la aplicación únicamente por HTTPS (TLS), redirigir o desactivar HTTP y sustituir HTTP Basic por un mecanismo de sesión o token sobre TLS.",
    "mqtt": "Usar MQTT sobre TLS (puerto 8883), credenciales individuales por cliente y ACL de topics en el broker.",
    "ftp": "Sustituir FTP por SFTP o FTPS; si no es posible, aislar el servicio en un segmento restringido.",
}
_REMEDIATION_COMMON = (
    "Cambiar las credenciales expuestas, que deben considerarse comprometidas. "
    "Segmentar la red y restringir quién puede observar el tráfico (puertos espejo, equipos con acceso al medio)."
)


def source_key(capture_sha: str, e: FlowEvent) -> str:
    """Identifica el origen de un hallazgo. Estable al reanalizar la captura (no usa ids de fila).
    Las credenciales se agrupan por flujo y protocolo (p. ej. FTP USER + PASS son un único hallazgo)."""
    base = f"{capture_sha[:16]}|{e.src_ip}>{e.dst_ip}:{e.transport}/{e.port}|{e.protocol}"
    return f"{base}|auth" if e.kind == "auth" else f"{base}|{e.kind}|{e.summary}"[:300]


def mask(value: str) -> str:
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


def _masked_summary(e: FlowEvent) -> str:
    text = e.summary
    for k in ("password", "authorization"):
        v = (e.detail or {}).get(k)
        if isinstance(v, str) and v:
            text = text.replace(v, mask(v))
    return text


def _when(e: FlowEvent) -> str:
    f = e.first_seen.strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{f} ({e.count} {'vez' if e.count == 1 else 'veces'})"


def build(db: Session, event: FlowEvent, capture: Capture) -> dict:
    """Campos de FindingCreate (sin identificador ni CVSS) para un evento."""
    label = LABEL.get(event.protocol, event.protocol)
    flow = f"{event.src_ip} → {event.dst_ip} {event.transport}/{event.port} ({label})"
    siblings = [event]
    if event.kind == "auth":
        siblings = list(db.scalars(select(FlowEvent).where(
            FlowEvent.capture_id == event.capture_id, FlowEvent.src_ip == event.src_ip, FlowEvent.dst_ip == event.dst_ip,
            FlowEvent.port == event.port, FlowEvent.transport == event.transport, FlowEvent.protocol == event.protocol, FlowEvent.kind == "auth",
        ).order_by(FlowEvent.id)))
    poc = [f"Captura: {capture.filename} (sha256 {capture.sha256[:16]}…)", f"Flujo (cliente → servidor): {flow}"]
    for s in siblings:
        poc.append(f"- {_masked_summary(s)} · primera vez: {_when(s)}")
        d = s.detail or {}
        if s.secret and d.get("user"):
            poc.append(f"    usuario: {d['user']}")
        if s.secret and d.get("password"):
            poc.append(f"    contraseña: {mask(str(d['password']))}")
        if d.get("client_id"):
            poc.append(f"    client_id: {d['client_id']}")
    poc.append("El valor completo se conserva en la captura analizada.")

    if event.kind == "auth":
        kinds = sorted({s.secret_kind for s in siblings if s.secret_kind})
        name = f"Credenciales transmitidas en claro ({label})"
        description = (f"En la captura «{capture.filename}» se observan credenciales enviadas sin cifrar mediante {label} entre el cliente {event.src_ip} "
                       f"y el servidor {event.dst_ip} ({event.transport}/{event.port}){': ' + ', '.join(kinds) if kinds else ''}.")
        impact = ("Cualquier equipo con acceso al medio de red (o que consiga situarse en la ruta) puede capturar las credenciales y reutilizarlas "
                  "para acceder al servicio con los privilegios de la cuenta expuesta.")
        recs = f"{_TLS_FIX.get(event.protocol, 'Cifrar el canal con TLS o usar un protocolo equivalente con cifrado.')} {_REMEDIATION_COMMON}"
    else:
        control = event.kind == "control"
        name = (f"Orden de control sobre el PLC observada en red ({label}: {event.summary})" if control
                else f"Operación de escritura observada en red ({label}: {event.summary})")[:300]
        description = (f"En la captura «{capture.filename}» se observa la operación «{event.summary}» de {label} del cliente {event.src_ip} "
                       f"hacia el servidor {event.dst_ip} ({event.transport}/{event.port}).")
        if event.protocol in NO_AUTH:
            description += f" {label} no incorpora autenticación nativa: el servidor no puede distinguir al emisor legítimo de cualquier otro equipo con acceso a la red."
            impact = ("Un equipo con acceso a esta red podría emitir órdenes equivalentes y alterar el proceso o detener el controlador, "
                      "sin necesidad de credenciales.")
        else:
            impact = "Un equipo con acceso a esta red podría observar y reproducir la operación o modificar el estado del servicio."
        description += " Esta evidencia procede de captura pasiva: debe contrastarse con la actividad legítima de la estación origen."
        recs = ("Restringir el acceso al puerto solo desde las estaciones autorizadas (firewall/ACL) y segmentar en zonas y conductos según IEC 62443; "
                "monitorizar las operaciones de escritura y control; activar la protección de acceso del dispositivo o usar un protocolo con autenticación.")
    assets = list(db.scalars(select(Asset).where(Asset.campaign_id == event.campaign_id, Asset.ip == event.dst_ip)))
    return {
        "name": name, "phase": "discovery", "status": "draft", "description": description, "poc": "\n".join(poc), "impact": impact,
        "recommendations": recs, "asset_ids": [a.id for a in assets],
        "affected_other": "" if assets else f"{event.dst_ip} (no registrado como activo)",
    }
