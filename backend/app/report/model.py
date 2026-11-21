"""Datos del informe, etiquetas i18n y constantes de marca."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

_LONG = 100_000


class ReportData(BaseModel):
    client: str = Field(default="", max_length=200)
    dut_name: str = Field(default="", max_length=200)  # sistema/dispositivo auditado (DUT)
    test_type: Literal["", "white", "grey", "black"] = ""
    language: Literal["es", "en"] = "es"
    version: str = Field(default="1.0", max_length=30)
    author: str = Field(default="", max_length=200)
    classification: str = Field(default="Confidencial", max_length=100)
    report_date: date | None = None  # vacío = fecha de generación
    introduction: str = Field(default="", max_length=_LONG)  # vacío = texto estándar
    methodology: str = Field(default="", max_length=_LONG)  # vacío = texto estándar
    dut_description: str = Field(default="", max_length=_LONG)
    exploitation_summary: str = Field(default="", max_length=_LONG)
    remediation_summary: str = Field(default="", max_length=_LONG)
    conclusions: str = Field(default="", max_length=_LONG)


DRAFTABLE = ("exploitation_summary", "remediation_summary", "conclusions")
PHASE_ORDER = ["discovery", "exploitation", "post_exploitation"]
RATING_ORDER = ["Critical", "High", "Medium", "Low", "None", ""]

# Paleta del informe. El cian solo se usa como acento decorativo (no como texto sobre blanco).
BLACK, ACCENT = "2D2A26", "0E9BB5"
GREY_FILL, GREY_LINE, GREY_TEXT = "F3F3F1", "D0D0CC", "6B6B66"
RATING_COLOR = {"Critical": "7B1020", "High": "C2410C", "Medium": "A16207", "Low": "2F7D32", "None": "6B7280", "": "6B7280"}
FONT, MONO = "Arial", "Courier New"

LABELS = {
    "es": {
        "title": "Informe de auditoría de seguridad", "toc": "Índice", "cover_meta": "Datos del informe",
        "client": "Cliente", "dut": "Sistema auditado (DUT)", "test_type": "Tipo de prueba", "version": "Versión", "date": "Fecha",
        "author": "Autor", "classification": "Clasificación",
        "test_types": {"white": "Caja blanca (white box)", "grey": "Caja gris (grey box)", "black": "Caja negra (black box)", "": "[PENDIENTE]"},
        "sections": ["Introducción", "Metodología", "Alcance", "Descripción del DUT", "Descubrimiento del sistema",
                     "Resumen de Explotación", "Resumen de Remediaciones", "Hallazgos", "Conclusiones"],
        "phases": {"discovery": "Descubrimiento", "exploitation": "Explotación", "post_exploitation": "Post-Explotación"},
        "f_id": "Identificador", "f_name": "Nombre", "f_crit": "Criticidad", "f_assets": "Activos afectados", "f_dep": "Requiere el hallazgo",
        "f_desc": "Descripción", "f_poc": "Prueba de concepto", "f_impact": "Impacto", "f_rec": "Recomendaciones",
        "evidence": "Evidencia", "pending": "PENDIENTE", "page": "Página", "of": "de",
        "scope_intro": "Las pruebas se han limitado a los siguientes activos, rangos y hosts:", "audit_type": "Tipo de auditoría",
        "period": "Periodo", "assets": "Activos identificados", "flows": "Comunicaciones observadas", "captures": "Capturas analizadas",
        "col_ip": "IP", "col_host": "Hostname", "col_mac": "MAC / fabricante", "col_ports": "Puertos abiertos",
        "col_src": "Origen (cliente)", "col_dst": "Destino (servidor)", "col_proto": "Protocolo", "col_port": "Puerto", "col_pkts": "Paquetes",
        "col_id": "ID", "col_name": "Nombre", "col_crit": "Criticidad", "col_phase": "Fase",
        "no_assets": "No se han registrado activos.", "no_flows": "No se han registrado comunicaciones.",
        "flows_more": "Se muestran las {n} comunicaciones con más tráfico de {total}.",
        "findings_summary": "Resumen de hallazgos", "no_findings": "No se han registrado hallazgos.",
        "intro_default": "El presente documento recoge los resultados de la auditoría de seguridad realizada sobre {dut}{client}. Incluye el alcance, los activos identificados, los hallazgos detectados con su criticidad, y las recomendaciones de remediación.",
        "method_default": "La auditoría se ha estructurado en tres fases: descubrimiento del sistema, explotación de las vulnerabilidades identificadas y post-explotación. La criticidad de cada hallazgo se expresa mediante su puntuación y vector CVSS.",
        "client_part": " para {client}",
    },
    "en": {
        "title": "Security Assessment Report", "toc": "Table of contents", "cover_meta": "Report details",
        "client": "Client", "dut": "Device under test (DUT)", "test_type": "Test type", "version": "Version", "date": "Date",
        "author": "Author", "classification": "Classification",
        "test_types": {"white": "White box", "grey": "Grey box", "black": "Black box", "": "[PENDING]"},
        "sections": ["Introduction", "Methodology", "Scope", "DUT Description", "System Discovery",
                     "Exploitation Summary", "Remediation Summary", "Findings", "Conclusions"],
        "phases": {"discovery": "Discovery", "exploitation": "Exploitation", "post_exploitation": "Post-Exploitation"},
        "f_id": "Identifier", "f_name": "Name", "f_crit": "Criticality", "f_assets": "Affected assets", "f_dep": "Requires finding",
        "f_desc": "Description", "f_poc": "Proof of Concept", "f_impact": "Impact", "f_rec": "Recommendations",
        "evidence": "Evidence", "pending": "PENDING", "page": "Page", "of": "of",
        "scope_intro": "Testing was limited to the following assets, ranges and hosts:", "audit_type": "Assessment type",
        "period": "Period", "assets": "Identified assets", "flows": "Observed communications", "captures": "Analysed captures",
        "col_ip": "IP", "col_host": "Hostname", "col_mac": "MAC / vendor", "col_ports": "Open ports",
        "col_src": "Source (client)", "col_dst": "Destination (server)", "col_proto": "Protocol", "col_port": "Port", "col_pkts": "Packets",
        "col_id": "ID", "col_name": "Name", "col_crit": "Criticality", "col_phase": "Phase",
        "no_assets": "No assets have been recorded.", "no_flows": "No communications have been recorded.",
        "flows_more": "Showing the {n} busiest communications out of {total}.",
        "findings_summary": "Findings summary", "no_findings": "No findings have been recorded.",
        "intro_default": "This document presents the results of the security assessment performed on {dut}{client}. It covers the scope, the identified assets, the findings detected with their criticality, and the remediation recommendations.",
        "method_default": "The assessment was structured in three phases: system discovery, exploitation of the identified vulnerabilities and post-exploitation. The criticality of each finding is expressed through its CVSS score and vector.",
        "client_part": " for {client}",
    },
}
