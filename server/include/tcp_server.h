#ifndef TCP_SERVER_H
#define TCP_SERVER_H

#include <stdint.h>
#include <stdbool.h>
#include <netinet/in.h>
#include <pthread.h>
#include "protocol_defs.h"

#define DEFAULT_TCP_PORT 8080
#define DEFAULT_UDP_PORT 8081

// Trạng thái mô phỏng bay của UAV
typedef struct {
    float lat;
    float lon;
    float alt;
    float roll;
    float pitch;
    float yaw;
    float speed;
    float battery;
    uint8_t flight_mode;

    float target_alt;
    WaypointItem active_waypoints[MAX_WAYPOINTS];
    uint16_t waypoint_count;
    uint16_t current_wp_index;

    pthread_mutex_t lock;
} UavSimState;

// Cấu hình Server
typedef struct {
    int tcp_port;              // Cổng TCP lắng nghe (mặc định 8080)
    int udp_port;              // Cổng UDP gửi Telemetry về Client (mặc định 8081)
    int tcp_listen_fd;         // Socket TCP lắng nghe
    int udp_fd;                // Socket UDP phát Telemetry
    volatile bool running;     // Cờ trạng thái máy chủ

    // Thông tin Client kết nối gần nhất để bắn UDP
    struct sockaddr_in client_udp_addr;
    bool has_client;
    pthread_mutex_t client_lock;

    // Trạng thái UAV mô phỏng
    UavSimState uav;
    pthread_t sim_thread;
} TcpServer;

// Khởi tạo máy chủ TCP & kênh UDP Telemetry
bool tcp_server_init(TcpServer *server, int tcp_port, int udp_port);

// Bắt đầu vòng lặp lắng nghe kết nối
void tcp_server_run(TcpServer *server);

// Dừng máy chủ
void tcp_server_stop(TcpServer *server);

// Hàm đọc chính xác n bytes từ TCP socket
int recv_exact(int sock_fd, void *buffer, size_t num_bytes);

// Chuyển đổi float 32-bit giữa Big-Endian và Host
float ntohf(float val);
float htonf(float val);

#endif // TCP_SERVER_H
