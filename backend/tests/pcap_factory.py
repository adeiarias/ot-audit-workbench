"""Genera pcaps sintéticos mínimos (Ethernet/IPv4/TCP|UDP, ARP) sin dependencias externas."""
import socket
import struct


def _mac(s: str) -> bytes:
    return bytes(int(x, 16) for x in s.split(":"))


def _ip_checksum(header: bytes) -> int:
    total = sum(struct.unpack(">10H", header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _ipv4(src: str, dst: str, proto: int, payload: bytes) -> bytes:
    hdr = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 0, 0, 64, proto, 0, socket.inet_aton(src), socket.inet_aton(dst))
    hdr = hdr[:10] + struct.pack(">H", _ip_checksum(hdr)) + hdr[12:]
    return hdr + payload


class Pcap:
    def __init__(self):
        self.packets: list[tuple[float, bytes]] = []
        self._seq: dict[tuple, int] = {}
        self.t = 1_700_000_000.0

    def _add(self, frame: bytes):
        self.t += 0.01
        self.packets.append((self.t, frame))

    def tcp(self, src, dst, sport, dport, payload, smac, dmac):
        key = (src, dst, sport, dport)
        seq = self._seq.get(key, 1000)
        self._seq[key] = seq + len(payload)
        # TCP: flags PSH|ACK, ventana fija; checksum sin calcular (tshark no la valida por defecto)
        seg = struct.pack(">HHIIBBHHH", sport, dport, seq, 1, 5 << 4, 0x18, 8192, 0, 0) + payload
        self._add(_mac(dmac) + _mac(smac) + b"\x08\x00" + _ipv4(src, dst, 6, seg))

    def udp(self, src, dst, sport, dport, payload, smac, dmac):
        seg = struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload
        self._add(_mac(dmac) + _mac(smac) + b"\x08\x00" + _ipv4(src, dst, 17, seg))

    def arp_reply(self, ip, mac, target_ip, target_mac):
        arp = struct.pack(">HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 2, _mac(mac), socket.inet_aton(ip), _mac(target_mac), socket.inet_aton(target_ip))
        self._add(_mac(target_mac) + _mac(mac) + b"\x08\x06" + arp)

    def raw_l2(self, smac, dmac, ethertype, payload):
        self._add(_mac(dmac) + _mac(smac) + struct.pack(">H", ethertype) + payload)

    def to_bytes(self) -> bytes:
        out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        for ts, frame in self.packets:
            sec = int(ts)
            out += struct.pack("<IIII", sec, int((ts - sec) * 1_000_000), len(frame), len(frame)) + frame
        return out


MODBUS_REQ = bytes.fromhex("000100000006010300000004")
MODBUS_RESP = bytes.fromhex("00010000000b010308") + bytes(range(8))

EWS, PLC, GW = "00:11:22:33:44:02", "00:11:22:33:44:05", "00:11:22:33:44:fe"


def demo_pcap() -> bytes:
    """Estación de ingeniería ↔ PLC (Modbus + HTTP), DNS hacia fuera, mDNS multicast, ARP y un frame L2 no IP."""
    p = Pcap()
    p.arp_reply("10.0.0.5", PLC, "10.0.0.2", EWS)
    for _ in range(3):
        p.tcp("10.0.0.2", "10.0.0.5", 40001, 502, MODBUS_REQ, EWS, PLC)
        p.tcp("10.0.0.5", "10.0.0.2", 502, 40001, MODBUS_RESP, PLC, EWS)
    p.tcp("10.0.0.2", "10.0.0.5", 40002, 80, b"GET / HTTP/1.1\r\nHost: plc\r\n\r\n", EWS, PLC)
    p.tcp("10.0.0.5", "10.0.0.2", 80, 40002, b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", PLC, EWS)
    p.udp("10.0.0.2", "8.8.8.8", 51000, 53, b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03abc\x00\x00\x01\x00\x01", EWS, GW)
    p.udp("10.0.0.5", "224.0.0.251", 5353, 5353, b"\x00" * 12, PLC, "01:00:5e:00:00:fb")
    p.raw_l2(PLC, "01:80:c2:00:00:0e", 0x88CC, b"\x02\x07\x04" + bytes(20))
    return p.to_bytes()


def _mqtt_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack(">H", len(b)) + b


def _mqtt(first: int, body: bytes) -> bytes:
    return bytes([first, len(body)]) + body  # remaining length < 128


def _s7(rosctr: int, param: bytes, data: bytes = b"", pdu_ref: int = 1) -> bytes:
    s7 = struct.pack(">BBHHHH", 0x32, rosctr, 0, pdu_ref, len(param), len(data)) + param + data
    cotp = b"\x02\xf0\x80"
    return struct.pack(">BBH", 3, 0, 4 + len(cotp) + len(s7)) + cotp + s7


_S7_ITEM = b"\x12\x0a\x10\x02"  # variable specification, sintaxid S7ANY, transporte BYTE


def protocols_pcap() -> bytes:
    """Una estación (10.0.0.2) hablando con servidores HTTP, MQTT, Modbus, S7 y FTP (10.0.0.5-.9), con credenciales en claro."""
    p = Pcap()
    cli = "10.0.0.2"
    # HTTP: petición con Basic (admin:secret) y un POST; 200 de respuesta
    p.tcp(cli, "10.0.0.5", 40100, 80, b"GET /login HTTP/1.1\r\nHost: plc.local\r\nUser-Agent: curl/8.0\r\nAuthorization: Basic YWRtaW46c2VjcmV0\r\n\r\n", EWS, PLC)
    p.tcp("10.0.0.5", cli, 80, 40100, b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\nok", PLC, EWS)
    body = b"cmd=stop"
    p.tcp(cli, "10.0.0.5", 40101, 80, b"POST /api/ctl HTTP/1.1\r\nHost: plc.local\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body), EWS, PLC)
    # MQTT: CONNECT con usuario/contraseña, SUBSCRIBE y dos PUBLISH al mismo topic
    connect = _mqtt(0x10, _mqtt_str("MQTT") + bytes([4, 0xC2]) + struct.pack(">H", 60) + _mqtt_str("sensor1") + _mqtt_str("mqttuser") + _mqtt_str("mqttpass"))
    p.tcp(cli, "10.0.0.6", 40200, 1883, connect, EWS, PLC)
    p.tcp(cli, "10.0.0.6", 40200, 1883, _mqtt(0x82, struct.pack(">H", 1) + _mqtt_str("plant/#") + b"\x00"), EWS, PLC)
    for v in (b"25.5", b"26.1"):
        p.tcp(cli, "10.0.0.6", 40200, 1883, _mqtt(0x30, _mqtt_str("plant/temp") + v), EWS, PLC)
    # Modbus: lectura de registros, escritura FC16 @10 (valores 1, 2) y respuesta de lectura
    p.tcp(cli, "10.0.0.7", 40300, 502, MODBUS_REQ, EWS, PLC)
    p.tcp("10.0.0.7", cli, 502, 40300, bytes.fromhex("00010000000b010308") + bytes.fromhex("0001000200030004"), PLC, EWS)
    p.tcp(cli, "10.0.0.7", 40300, 502, bytes.fromhex("0002000000" "0b0110000a000204") + bytes.fromhex("00010002"), EWS, PLC)
    # S7: lectura DB1.DBX0.0, escritura DB1.DBX0.0 y parada de la CPU
    p.tcp(cli, "10.0.0.8", 40400, 102, _s7(1, b"\x04\x01" + _S7_ITEM + struct.pack(">HHB", 1, 1, 0x84) + b"\x00\x00\x00"), EWS, PLC)
    p.tcp(cli, "10.0.0.8", 40400, 102, _s7(1, b"\x05\x01" + _S7_ITEM + struct.pack(">HHB", 1, 1, 0x84) + b"\x00\x00\x00", b"\x00\x04\x00\x08\x01", 2), EWS, PLC)
    p.tcp(cli, "10.0.0.8", 40400, 102, _s7(1, b"\x29\x00\x00\x00\x00\x00\x09P_PROGRAM", pdu_ref=3), EWS, PLC)
    # FTP: login en claro, subida y respuesta de login
    for line in (b"USER admin\r\n", b"PASS hunter2\r\n", b"STOR firmware.bin\r\n"):
        p.tcp(cli, "10.0.0.9", 40500, 21, line, EWS, PLC)
    p.tcp("10.0.0.9", cli, 21, 40500, b"230 Login successful.\r\n", PLC, EWS)
    return p.to_bytes()
