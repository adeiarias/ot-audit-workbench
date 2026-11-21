import struct
import zlib


def real_png(w: int = 400, h: int = 225, rgb=(40, 90, 160)) -> bytes:
    """PNG válido (rayas) para que python-docx pueda leer sus dimensiones."""
    rows = b"".join(b"\x00" + bytes(rgb if (y // 15) % 2 == 0 else tuple(max(0, v - 40) for v in rgb)) * w for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
