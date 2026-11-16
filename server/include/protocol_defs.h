#ifndef PROTOCOL_DEFS_H
#define PROTOCOL_DEFS_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define SYNC_MAGIC 0xBEEF // Chữ ký đồng bộ 2 bytes (0xBEEF)
#define MAX_WAYPOINTS 50  // Số điểm tọa độ tối đa trong 1 gói CMD_WAYPOINT

// Bảng mã lệnh OpCode (msg_type) chuẩn theo giao thức
typedef enum {
    OP_AUTH_REQ     = 0x01, // Client gửi thông tin đăng nhập (48 bytes)
    OP_AUTH_RES     = 0x02, // Server phản hồi kết quả xác thực (33 bytes)
    OP_TELEMETRY    = 0x03, // UAV truyền tọa độ, IMU, Pin (UDP 20Hz - 34 bytes)
    OP_CMD_WAYPOINT = 0x04, // Client gửi danh sách tọa độ hành trình (802 bytes)
    OP_CMD_ACTION   = 0x05, // Lệnh can thiệp tức thời (1: Takeoff, 2: Land, 3: RTL)
    OP_PING         = 0x0A, // Server kiểm tra kết nối định kỳ
    OP_PONG         = 0x0B  // Client phản hồi nhịp tim
} opcode_t;

// Mã lệnh hành động cho OP_CMD_ACTION (0x05)
typedef enum {
    ACTION_TAKEOFF = 1, // Cất cánh
    ACTION_LAND    = 2, // Hạ cánh
    ACTION_RTL     = 3  // Bay về trạm (Return To Launch)
} action_type_t;

// Chế độ bay trong TELEMETRY (0x03)
typedef enum {
    FLIGHT_MODE_IDLE    = 0, // Đang chờ dưới đất
    FLIGHT_MODE_MISSION = 1, // Đang bay theo hành trình Waypoint
    FLIGHT_MODE_AUTO_RTL= 2, // Tự động bay về trạm
    FLIGHT_MODE_LANDED  = 3  // Đã hạ cánh
} flight_mode_t;

// Ép cấu trúc 1-byte alignment chống Byte-Padding
#pragma pack(push, 1)

// Header cố định 8 bytes: >HBBI (Big-Endian)
typedef struct {
    uint16_t magic;       // 2 bytes: 0xBEEF
    uint8_t  msg_type;    // 1 byte: OpCode (0x01 .. 0x0B)
    uint8_t  status;      // 1 byte: 0: OK, >0: Mã lỗi
    uint32_t payload_len; // 4 bytes: Chiều dài payload theo sau
} MessageHeader;

// 0x01: AUTH_REQ (48 bytes)
typedef struct {
    char device_id[16];   // ID thiết bị (đệm 0x00)
    char secret_key[32];  // Mật khẩu bí mật
} AuthReqPayload;

// 0x02: AUTH_RES (33 bytes)
typedef struct {
    uint8_t status_code;    // 0: Thành công, >0: Mã lỗi
    char session_token[32]; // Token phiên làm việc
} AuthResPayload;

// Cấu trúc 1 điểm tọa độ Waypoint (16 bytes)
typedef struct {
    float latitude;   // Vĩ độ (deg)
    float longitude;  // Kinh độ (deg)
    float altitude;   // Độ cao (m)
    float speed;      // Vận tốc bay (m/s)
} WaypointItem;

// 0x04: CMD_WAYPOINT (802 bytes cố định)
typedef struct {
    uint16_t waypoint_count;               // 2 bytes: Số điểm thực tế (1 .. 50)
    WaypointItem waypoints[MAX_WAYPOINTS]; // 50 * 16 = 800 bytes
} CmdWaypointPayload;

// 0x05: CMD_ACTION (1 byte)
typedef struct {
    uint8_t action_type; // 1: Takeoff, 2: Land, 3: RTL
} CmdActionPayload;

// 0x03: TELEMETRY (34 bytes - UDP 20Hz)
typedef struct {
    uint32_t timestamp_ms; // Thời gian bay (ms)
    float latitude;        // Vĩ độ
    float longitude;       // Kinh độ
    float altitude;        // Độ cao (m)
    float roll;            // Góc nghiêng ngang
    float pitch;           // Góc nghiêng dọc
    float yaw;             // Hướng bay (deg)
    float speed;           // Vận tốc (m/s)
    uint8_t battery;       // Dung lượng pin (0-100%)
    uint8_t flight_mode;   // Chế độ bay (flight_mode_t)
} TelemetryPayload;

#pragma pack(pop)

#endif // PROTOCOL_DEFS_H

