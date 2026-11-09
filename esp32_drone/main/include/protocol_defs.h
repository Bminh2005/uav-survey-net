#ifndef PROTOCOL_DEFS_H
#define PROTOCOL_DEFS_H

#include <stdint.h>

#define SYNC_MAGIC 0xBEEF // Chu kỳ đồng bộ 2 bytes (0xBEEF)

// Tập mã lệnh OpCode (msg_type)
typedef enum
{
    MSG_AUTH_INIT = 0x01,      // UAV gửi Device ID xin Challenge/Nonce
    MSG_AUTH_CHALLENGE = 0x02, // Server trả về Nonce ngẫu nhiên
    MSG_AUTH_REQ = 0x03,       // UAV gửi HMAC-SHA256 Response
    MSG_AUTH_RES = 0x04,       // Kết quả xác thực từ Server[cite: 3]
    MSG_TELEMETRY = 0x03,      // UDP Telemetry (theo bảng tập lệnh gốc)[cite: 3]
    MSG_PING = 0x0A,           // Heartbeat PING[cite: 3]
    MSG_PONG = 0x0B            // Heartbeat PONG[cite: 3]
} msg_type_t;

// Ép cấu hình 1 byte per alignment để tránh Byte-Padding
#pragma pack(push, 1)

// Header cố định 8 bytes[cite: 2]
typedef struct
{
    uint16_t magic;       // 2 bytes: 0xBEEF[cite: 2]
    uint8_t msg_type;     // 1 byte: OpCode[cite: 2]
    uint8_t status;       // 1 byte: Trạng thái lỗi[cite: 2]
    uint32_t payload_len; // 4 bytes: Độ dài payload (Network Byte Order)[cite: 2]
} MessageHeader;

// Payload Bước 1: Gửi Device ID
typedef struct
{
    char device_id[16]; // VD: "UAV_ESP32_01"
} AuthInitPayload;

// Payload Bước 2: Server trả về Nonce ngẫu nhiên 16 bytes
typedef struct
{
    uint8_t nonce[16];
} AuthChallengePayload;

// Payload Bước 3: UAV gửi HMAC-SHA256 (32 bytes)
typedef struct
{
    char device_id[16];
    uint8_t response_hash[32]; // HMAC_SHA256(SecretKey, Nonce)
} AuthReqPayload;

// Payload Bước 4: Server phản hồi kết quả
typedef struct
{
    uint8_t status_code; // 0: Thành công, >0: Thất bại
    char session_token[32];
} AuthResPayload;

#pragma pack(pop)

// Hàm hỗ trợ chuyển đổi Byte-Order cho Header[cite: 3]
void header_to_network(MessageHeader *hdr);
void header_to_host(MessageHeader *hdr);

#endif // PROTOCOL_DEFS_H