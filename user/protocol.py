"""
Định nghĩa giao thức nhị phân (Binary Protocol) cho Hệ thống Điều khiển UAV (Đề tài 11).
Tuân thủ 100% tài liệu giaothuc.pdf và project_spec.md:
- Byte-Order: Big-Endian (Network Byte Order `>`) cho toàn bộ số nguyên và số thực (float).
- Header cố định 8 bytes (`>HBBI`):
    uint16_t magic       = 0xBEEF
    uint8_t  msg_type    = OpCode (0x01 .. 0x0B)
    uint8_t  status      = 0: OK, 1-255: Mã lỗi
    uint32_t payload_len = Chiều dài Payload đi sau (Bytes)
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Tuple

# Hằng số Header
MAGIC_WORD: int = 0xBEEF
HEADER_FORMAT: str = ">HBBI"
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 8 bytes

# Giới hạn số lượng Waypoint tối đa trong 1 gói CMD_WAYPOINT
MAX_WAYPOINTS: int = 50


class OpCode(IntEnum):
    """Bảng mã lệnh điều khiển (msg_type trong MessageHeader)."""
    AUTH_REQ = 0x01      # User/UAV yêu cầu đăng nhập
    AUTH_RES = 0x02      # Server trả về trạng thái xác thực
    TELEMETRY = 0x03     # UAV truyền tọa độ, IMU, Pin (UDP 20Hz)
    CMD_WAYPOINT = 0x04  # User nạp danh sách hành trình khảo sát
    CMD_ACTION = 0x05    # Lệnh can thiệp tức thời (1: Takeoff, 2: Land, 3: RTL)
    PING = 0x0A          # Server kiểm tra kết nối (chu kỳ 2s)
    PONG = 0x0B          # Phản hồi nhịp tim


class ActionType(IntEnum):
    """Mã lệnh cho gói CMD_ACTION (0x05)."""
    TAKEOFF = 1  # Cất cánh
    LAND = 2     # Hạ cánh
    RTL = 3      # Bay về trạm (Return To Launch)


class FlightMode(IntEnum):
    """Chế độ bay trong gói TELEMETRY (0x03)."""
    IDLE = 0      # Đang chờ dưới đất
    MISSION = 1   # Đang bay theo hành trình Waypoint
    AUTO_RTL = 2  # Tự động bay về trạm (Safe RTL / Failsafe)
    LANDED = 3    # Đã hạ cánh

    def label_vi(self) -> str:
        labels = {
            FlightMode.IDLE: "0: IDLE (Chờ lệnh)",
            FlightMode.MISSION: "1: MISSION (Bay khảo sát)",
            FlightMode.AUTO_RTL: "2: AUTO-RTL (Failsafe về trạm)",
            FlightMode.LANDED: "3: LANDED (Đã hạ cánh)",
        }
        return labels.get(self, f"{int(self)}: UNKNOWN")


def _encode_fixed_str(text: str, length: int) -> bytes:
    """Mã hóa chuỗi sang mảng char[length] cố định, đệm byte 0x00 ở cuối."""
    raw = text.encode("utf-8")[:length]
    return raw.ljust(length, b"\x00")


def _decode_fixed_str(raw: bytes) -> str:
    """Giải mã mảng char[length] từ C (cắt bỏ từ byte 0x00 đầu tiên)."""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


@dataclass
class MessageHeader:
    """
    Cấu trúc Header cố định 8 bytes (`#pragma pack(push, 1)`):
        uint16_t magic;       // 0xBEEF - Chữ ký đồng bộ
        uint8_t  msg_type;    // Mã lệnh (OpCode)
        uint8_t  status;      // 0: OK, 1-255: Mã lỗi
        uint32_t payload_len; // Chiều dài Payload theo sau
    """
    msg_type: int
    status: int = 0
    payload_len: int = 0
    magic: int = MAGIC_WORD

    FORMAT = HEADER_FORMAT
    SIZE = HEADER_SIZE

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.magic & 0xFFFF,
            self.msg_type & 0xFF,
            self.status & 0xFF,
            self.payload_len & 0xFFFFFFFF,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "MessageHeader":
        if len(data) != cls.SIZE:
            raise ValueError(f"Header phải đúng {cls.SIZE} bytes, nhận được {len(data)} bytes")
        magic, msg_type, status, payload_len = struct.unpack(cls.FORMAT, data)
        if magic != MAGIC_WORD:
            raise ValueError(f"Sai chữ ký đồng bộ magic: 0x{magic:04X} (kỳ vọng 0x{MAGIC_WORD:04X})")
        return cls(
            magic=magic,
            msg_type=msg_type,
            status=status,
            payload_len=payload_len,
        )


@dataclass
class AuthReqPayload:
    """
    0x01: AUTH_REQ (48 bytes)
        char device_id[16];
        char secret_key[32];
    """
    device_id: str
    secret_key: str

    FORMAT = ">16s32s"
    SIZE = struct.calcsize(FORMAT)  # 48 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            _encode_fixed_str(self.device_id, 16),
            _encode_fixed_str(self.secret_key, 32),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "AuthReqPayload":
        if len(data) != cls.SIZE:
            raise ValueError(f"AuthReqPayload phải đúng {cls.SIZE} bytes, nhận được {len(data)} bytes")
        dev_raw, key_raw = struct.unpack(cls.FORMAT, data)
        return cls(
            device_id=_decode_fixed_str(dev_raw),
            secret_key=_decode_fixed_str(key_raw),
        )


@dataclass
class AuthResPayload:
    """
    0x02: AUTH_RES (33 bytes)
        uint8_t status_code;    // 0: Thành công, >0: Mã lỗi
        char session_token[32]; // Token phiên làm việc
    """
    status_code: int
    session_token: str = ""

    FORMAT = ">B32s"
    SIZE = struct.calcsize(FORMAT)  # 33 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.status_code & 0xFF,
            _encode_fixed_str(self.session_token, 32),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "AuthResPayload":
        if len(data) != cls.SIZE:
            raise ValueError(f"AuthResPayload phải đúng {cls.SIZE} bytes, nhận được {len(data)} bytes")
        status_code, token_raw = struct.unpack(cls.FORMAT, data)
        return cls(
            status_code=status_code,
            session_token=_decode_fixed_str(token_raw),
        )


@dataclass
class TelemetryPayload:
    """
    0x03: TELEMETRY (34 bytes - UDP 20Hz)
        uint32_t timestamp_ms;
        float latitude;
        float longitude;
        float altitude;
        float roll;
        float pitch;
        float yaw;
        float speed;
        uint8_t battery;
        uint8_t flight_mode;
    """
    timestamp_ms: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    speed: float = 0.0
    battery: int = 100
    flight_mode: int = int(FlightMode.IDLE)

    FORMAT = ">I7f2B"
    SIZE = struct.calcsize(FORMAT)  # 34 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            self.timestamp_ms & 0xFFFFFFFF,
            float(self.latitude),
            float(self.longitude),
            float(self.altitude),
            float(self.roll),
            float(self.pitch),
            float(self.yaw),
            float(self.speed),
            max(0, min(100, int(self.battery))) & 0xFF,
            int(self.flight_mode) & 0xFF,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "TelemetryPayload":
        if len(data) != cls.SIZE:
            raise ValueError(f"TelemetryPayload phải đúng {cls.SIZE} bytes, nhận được {len(data)} bytes")
        (
            timestamp_ms,
            latitude,
            longitude,
            altitude,
            roll,
            pitch,
            yaw,
            speed,
            battery,
            flight_mode,
        ) = struct.unpack(cls.FORMAT, data)
        return cls(
            timestamp_ms=timestamp_ms,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            roll=roll,
            pitch=pitch,
            yaw=yaw,
            speed=speed,
            battery=battery,
            flight_mode=flight_mode,
        )


@dataclass
class WaypointItem:
    """
    Phần tử hành trình đơn lẻ (16 bytes):
        float latitude;
        float longitude;
        float altitude;
        float speed;
    """
    latitude: float
    longitude: float
    altitude: float
    speed: float

    FORMAT = ">4f"
    SIZE = struct.calcsize(FORMAT)  # 16 bytes

    def pack(self) -> bytes:
        return struct.pack(
            self.FORMAT,
            float(self.latitude),
            float(self.longitude),
            float(self.altitude),
            float(self.speed),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "WaypointItem":
        if len(data) != cls.SIZE:
            raise ValueError(f"WaypointItem phải đúng {cls.SIZE} bytes, nhận được {len(data)} bytes")
        lat, lon, alt, speed = struct.unpack(cls.FORMAT, data)
        return cls(latitude=lat, longitude=lon, altitude=alt, speed=speed)


@dataclass
class CmdWaypointPayload:
    """
    0x04: CMD_WAYPOINT (802 bytes cố định theo struct C `waypoints[50]`)
        uint16_t waypoint_count;
        struct WaypointItem waypoints[50];
    """
    waypoints: List[WaypointItem] = field(default_factory=list)

    COUNT_FORMAT = ">H"
    SIZE = 2 + MAX_WAYPOINTS * WaypointItem.SIZE  # 802 bytes

    def pack(self) -> bytes:
        if len(self.waypoints) > MAX_WAYPOINTS:
            raise ValueError(f"Tối đa {MAX_WAYPOINTS} waypoints, hiện có {len(self.waypoints)}")
        count = len(self.waypoints)
        buf = bytearray(struct.pack(self.COUNT_FORMAT, count))
        for wp in self.waypoints:
            buf.extend(wp.pack())
        # Đệm đủ 50 phần tử (0.0f) để khớp `sizeof(struct CmdWaypointPayload)` = 802 bytes bên C/C++
        padding_count = MAX_WAYPOINTS - count
        if padding_count > 0:
            buf.extend(b"\x00" * (padding_count * WaypointItem.SIZE))
        return bytes(buf)

    @classmethod
    def unpack(cls, data: bytes) -> "CmdWaypointPayload":
        if len(data) < 2:
            raise ValueError(f"CmdWaypointPayload quá ngắn: {len(data)} bytes")
        (count,) = struct.unpack(cls.COUNT_FORMAT, data[:2])
        if count > MAX_WAYPOINTS:
            raise ValueError(f"waypoint_count không hợp lệ: {count} (> {MAX_WAYPOINTS})")
        expected_min_len = 2 + count * WaypointItem.SIZE
        if len(data) < expected_min_len:
            raise ValueError(
                f"Dữ liệu CmdWaypointPayload không đủ cho {count} điểm "
                f"(cần ít nhất {expected_min_len} bytes, có {len(data)} bytes)"
            )
        items: List[WaypointItem] = []
        offset = 2
        for _ in range(count):
            item_bytes = data[offset : offset + WaypointItem.SIZE]
            items.append(WaypointItem.unpack(item_bytes))
            offset += WaypointItem.SIZE
        return cls(waypoints=items)


@dataclass
class CmdActionPayload:
    """
    0x05: CMD_ACTION (1 byte)
        uint8_t action_type; // 1: Takeoff, 2: Land, 3: RTL
    """
    action_type: int

    FORMAT = ">B"
    SIZE = struct.calcsize(FORMAT)  # 1 byte

    def pack(self) -> bytes:
        if self.action_type not in (ActionType.TAKEOFF, ActionType.LAND, ActionType.RTL):
            raise ValueError(f"action_type không hợp lệ: {self.action_type} (chỉ nhận 1, 2, 3)")
        return struct.pack(self.FORMAT, int(self.action_type) & 0xFF)

    @classmethod
    def unpack(cls, data: bytes) -> "CmdActionPayload":
        if len(data) != cls.SIZE:
            raise ValueError(f"CmdActionPayload phải đúng {cls.SIZE} byte, nhận được {len(data)} bytes")
        (action_type,) = struct.unpack(cls.FORMAT, data)
        return cls(action_type=action_type)


def pack_message(msg_type: int, payload_bytes: bytes = b"", status: int = 0) -> bytes:
    """Đóng gói hoàn chỉnh [MessageHeader (8B) + Payload] để gửi qua Socket."""
    header = MessageHeader(
        magic=MAGIC_WORD,
        msg_type=int(msg_type),
        status=status,
        payload_len=len(payload_bytes),
    )
    return header.pack() + payload_bytes


def recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    """
    Đọc chính xác `num_bytes` từ TCP socket bằng vòng lặp `while`
    (Chống dính/cắt gói TCP theo đúng quy tắc trang 3 của giaothuc.pdf).
    Ném ConnectionError nếu phía bên kia đóng kết nối (recv trả về b"").
    """
    buf = bytearray()
    while len(buf) < num_bytes:
        chunk = sock.recv(num_bytes - len(buf))
        if not chunk:
            raise ConnectionError("Kết nối TCP đã bị đóng từ phía đối tác (recv() == 0)")
        buf.extend(chunk)
    return bytes(buf)


def recv_tcp_message(sock: socket.socket) -> Tuple[MessageHeader, bytes]:
    """
    Đọc 1 thông điệp hoàn chỉnh từ luồng TCP:
    1. Đọc đúng 8 bytes đầu tiên để giải mã MessageHeader.
    2. Dùng vòng lặp while (recv_exact) đọc đủ số byte của payload_len.
    """
    header_bytes = recv_exact(sock, HEADER_SIZE)
    header = MessageHeader.unpack(header_bytes)
    payload_bytes = b""
    if header.payload_len > 0:
        payload_bytes = recv_exact(sock, header.payload_len)
    return header, payload_bytes
