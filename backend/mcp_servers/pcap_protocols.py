"""Extracción de contenido de protocolo (HTTP, MQTT, Modbus/TCP, S7comm, FTP) de una fila de tshark.

Independiente de `app/` (como el resto de servidores MCP). Cada fila ya viene filtrada por tshark y se convierte en un
evento: {protocol, direction, kind, summary, detail, secret, secret_kind}. El servidor los agrega por flujo y resumen.

kind: request | response | write (modifica estado) | control (parada/arranque/descarga de PLC) | auth (lleva credenciales)
"""
import base64
import re

DISPLAY_FILTER = "http || mqtt || mbtcp || s7comm || ftp"
SEP = "|"  # separador de valores múltiples de un mismo campo (-E aggregator)

FIELDS = [
    "http.request.method", "http.request.uri", "http.host", "http.response.code", "http.user_agent", "http.authorization", "http.content_type",
    "mqtt.msgtype", "mqtt.clientid", "mqtt.username", "mqtt.passwd", "mqtt.topic", "mqtt.msg",
    "modbus.func_code", "modbus.reference_num", "modbus.word_cnt", "modbus.bit_cnt", "modbus.exception_code", "modbus.regval_uint16", "modbus.data",
    "s7comm.header.rosctr", "s7comm.param.func", "s7comm.param.item.area", "s7comm.param.item.db", "s7comm.param.item.address",
    "ftp.request.command", "ftp.request.arg", "ftp.response.code", "ftp.response.arg",
]
N = len(FIELDS)
_IDX = {name: i for i, name in enumerate(FIELDS)}

MQTT_TYPES = {"1": "CONNECT", "3": "PUBLISH", "8": "SUBSCRIBE", "10": "UNSUBSCRIBE"}  # el resto (acks, pings) es ruido
MODBUS_FC = {1: "Read Coils", 2: "Read Discrete Inputs", 3: "Read Holding Registers", 4: "Read Input Registers", 5: "Write Single Coil",
             6: "Write Single Register", 8: "Diagnostics", 15: "Write Multiple Coils", 16: "Write Multiple Registers",
             22: "Mask Write Register", 23: "Read/Write Multiple Registers", 43: "Encapsulated Interface (Device ID)"}
MODBUS_WRITES = {5, 6, 15, 16, 22, 23}
S7_FUNC = {0x00: "CPU services", 0xF0: "Setup communication", 0x04: "Read Var", 0x05: "Write Var", 0x1A: "Request download",
           0x1B: "Download block", 0x1C: "Download ended", 0x1D: "Start upload", 0x1E: "Upload", 0x1F: "End upload",
           0x28: "PLC control", 0x29: "PLC stop"}
S7_WRITE, S7_CONTROL = {0x05}, {0x1A, 0x1B, 0x1C, 0x28, 0x29}
S7_AREA = {0x81: "I", 0x82: "Q", 0x83: "M", 0x84: "DB", 0x1C: "C", 0x1D: "T"}
FTP_WRITE = {"STOR", "STOU", "APPE", "DELE", "RMD", "MKD", "RNFR", "RNTO", "SITE"}
MAX_TEXT = 160


def _txt(value: str, limit: int = MAX_TEXT) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _bytes_preview(hexstr: str) -> str:
    """Campo FT_BYTES (hex, a veces con ':') → texto si es imprimible, si no hex."""
    raw = hexstr.replace(":", "")
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return _txt(hexstr)
    try:
        text = data.decode("utf-8")
        if text.isprintable():
            return _txt(text)
    except UnicodeDecodeError:
        pass
    return _txt(raw[:64] + ("…" if len(raw) > 64 else ""))


def _ints(value: str) -> list[int]:
    out = []
    for part in value.split(SEP):
        try:
            out.append(int(part, 0))
        except ValueError:
            pass
    return out


def _ev(protocol, direction, kind, summary, detail=None, secret=False, secret_kind=""):
    return {"protocol": protocol, "direction": direction, "kind": kind, "summary": _txt(summary, 300),
            "detail": detail or {}, "secret": secret, "secret_kind": secret_kind}


def _http(g, direction):
    method, uri, host = g("http.request.method"), g("http.request.uri"), g("http.host")
    if method:
        detail = {k: v for k, v in (("host", host), ("user_agent", g("http.user_agent")), ("content_type", g("http.content_type"))) if v}
        auth = g("http.authorization")
        if auth:
            scheme, _, cred = auth.partition(" ")
            if scheme.lower() == "basic":
                try:
                    user, _, pwd = base64.b64decode(cred).decode("utf-8", "replace").partition(":")
                except ValueError:
                    user, pwd = "", cred
                return _ev("http", direction, "auth", f"{method} {_txt(uri)}", {**detail, "user": user, "password": pwd}, True, "HTTP Basic")
            return _ev("http", direction, "auth", f"{method} {_txt(uri)}", {**detail, "authorization": _txt(auth, 200)}, True, f"HTTP {scheme or 'Authorization'}")
        return _ev("http", direction, "write" if method.upper() in {"POST", "PUT", "DELETE", "PATCH"} else "request", f"{method} {_txt(uri)}", detail)
    code = g("http.response.code")
    if code:
        return _ev("http", direction, "response", f"HTTP {code}", {"content_type": g("http.content_type")} if g("http.content_type") else None)
    return None


def _mqtt(g, direction):
    kind = MQTT_TYPES.get(g("mqtt.msgtype").split(SEP)[0])
    if not kind:
        return None
    topics = [t for t in g("mqtt.topic").split(SEP) if t]
    if kind == "CONNECT":
        user, pwd = g("mqtt.username"), g("mqtt.passwd")
        detail = {k: v for k, v in (("client_id", g("mqtt.clientid")), ("user", user), ("password", pwd)) if v}
        return _ev("mqtt", direction, "auth" if (user or pwd) else "request", f"CONNECT client={g('mqtt.clientid') or '?'}", detail,
                   bool(user or pwd), "MQTT CONNECT" if (user or pwd) else "")
    topic = ", ".join(topics) or "?"
    detail = {"sample": _bytes_preview(g("mqtt.msg"))} if kind == "PUBLISH" and g("mqtt.msg") else None
    return _ev("mqtt", direction, "write" if kind == "PUBLISH" else "request", f"{kind} {topic}", detail)


def _modbus(g, direction):
    fcs = _ints(g("modbus.func_code"))
    if not fcs:
        return None
    raw = fcs[0]
    fc, exc = raw & 0x7F, g("modbus.exception_code")
    name = MODBUS_FC.get(fc, f"función {fc}")
    if exc or raw >= 0x80:
        return _ev("modbus", direction, "response", f"FC{fc} {name} → excepción {exc or '?'}")
    ref, qty = g("modbus.reference_num"), g("modbus.word_cnt") or g("modbus.bit_cnt")
    values = [str(v) for v in _ints(g("modbus.regval_uint16"))][:16]
    if not values and g("modbus.data"):  # escrituras: tshark deja los valores como bytes crudos (palabras de 16 bits big-endian)
        try:
            raw_data = bytes.fromhex(g("modbus.data").replace(":", ""))
            values = [str(int.from_bytes(raw_data[i:i + 2], "big")) for i in range(0, len(raw_data) - 1, 2)][:16]
        except ValueError:
            pass
    if direction == "c2s":
        where = f" @{ref}" if ref != "" else ""
        n = f" ×{qty}" if qty else ""
        return _ev("modbus", direction, "write" if fc in MODBUS_WRITES else "request", f"FC{fc} {name}{where}{n}", {"values": values} if values else None)
    return _ev("modbus", direction, "response", f"FC{fc} {name} → respuesta", {"values": values} if values else None)


def _s7(g, direction):
    func_s, rosctr = g("s7comm.param.func"), g("s7comm.header.rosctr")
    if not func_s and not rosctr:
        return None
    func = _ints(func_s)[0] if func_s else None
    if direction == "s2c" or rosctr in ("2", "3"):
        return _ev("s7", "s2c", "response", f"{S7_FUNC.get(func, 'S7')} → respuesta") if func is not None else None
    if func is None:
        return None
    name = S7_FUNC.get(func, f"función 0x{func:02x}")
    kind = "control" if func in S7_CONTROL else "write" if func in S7_WRITE else "request"
    items = []
    if func in (0x04, 0x05):
        areas, dbs, addrs = _ints(g("s7comm.param.item.area")), _ints(g("s7comm.param.item.db")), _ints(g("s7comm.param.item.address"))
        for i, addr in enumerate(addrs):
            area = S7_AREA.get(areas[i] if i < len(areas) else -1, "?")
            db = f"{dbs[i]}." if area == "DB" and i < len(dbs) else ""
            items.append(f"{area}{db}{addr >> 3}.{addr & 7}")
    return _ev("s7", direction, kind, f"{name}" + (f" {', '.join(items)}" if items else ""), {"items": items} if items else None)


def _ftp(g, direction):
    cmd = g("ftp.request.command").upper()
    if cmd:
        arg = g("ftp.request.arg")
        if cmd == "USER":
            return _ev("ftp", direction, "auth", f"USER {arg}", {"user": arg}, True, "FTP USER")
        if cmd == "PASS":
            return _ev("ftp", direction, "auth", f"PASS {arg}", {"password": arg}, True, "FTP PASS")
        return _ev("ftp", direction, "write" if cmd in FTP_WRITE else "request", f"{cmd} {_txt(arg)}".strip())
    code = g("ftp.response.code")
    if code:
        return _ev("ftp", direction, "response", f"{code} {_txt(g('ftp.response.arg'), 100)}".strip())
    return None


def event_from_columns(cols: list[str], direction: str) -> dict | None:
    """cols = valores de FIELDS en orden. direction: c2s (cliente→servidor) | s2c."""
    def g(name: str) -> str:
        return cols[_IDX[name]]

    if g("http.request.method") or g("http.response.code"):
        return _http(g, direction)
    if g("mqtt.msgtype"):
        return _mqtt(g, direction)
    if g("modbus.func_code"):
        return _modbus(g, direction)
    if g("s7comm.param.func") or g("s7comm.header.rosctr"):
        return _s7(g, direction)
    if g("ftp.request.command") or g("ftp.response.code"):
        return _ftp(g, direction)
    return None
