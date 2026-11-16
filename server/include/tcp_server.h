#ifndef TCP_SERVER_H
#define TCP_SERVER_H

#include <stdint.h>
#include <stdbool.h>
#include <netinet/in.h>
#include "protocol_defs.h"

// Cấu hình Server
typedef struct {
    int port;                  // Cổng TCP lắng nghe (mặc định 8080)
    int listen_fd;             // File descriptor của socket lắng nghe
    volatile bool running;     // Cờ trạng thái máy chủ
} TcpServer;

// Khởi tạo máy chủ TCP
bool tcp_server_init(TcpServer *server, int port);

// Bắt đầu vòng lặp lắng nghe và xử lý kết nối từ Client
void tcp_server_run(TcpServer *server);

// Dừng máy chủ
void tcp_server_stop(TcpServer *server);

// Hàm đọc chính xác n bytes từ TCP socket (chống dính / cắt gói tin)
int recv_exact(int sock_fd, void *buffer, size_t num_bytes);

// Chuyển đổi số thực 32-bit (float) giữa Big-Endian (Network) và Host Byte Order
float ntohf(float val);
float htonf(float val);

#endif // TCP_SERVER_H

