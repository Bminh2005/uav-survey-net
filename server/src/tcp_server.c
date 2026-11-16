#include "tcp_server.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <math.h>

// Màu sắc terminal để in log trực quan
#define COLOR_RESET   "\033[0m"
#define COLOR_GREEN   "\033[1;32m"
#define COLOR_CYAN    "\033[1;36m"
#define COLOR_YELLOW  "\033[1;33m"
#define COLOR_RED     "\033[1;31m"
#define COLOR_MAGENTA "\033[1;35m"

#define BUFFER_SIZE 2048

// Chuyển đổi float 32-bit giữa Big-Endian (Network) và Host
float ntohf(float val) {
    uint32_t tmp;
    memcpy(&tmp, &val, sizeof(tmp));
    tmp = ntohl(tmp);
    float res;
    memcpy(&res, &tmp, sizeof(res));
    return res;
}

float htonf(float val) {
    uint32_t tmp;
    memcpy(&tmp, &val, sizeof(tmp));
    tmp = htonl(tmp);
    float res;
    memcpy(&res, &tmp, sizeof(res));
    return res;
}

// Đọc chính xác num_bytes từ TCP socket (Chống dính / cắt gói)
int recv_exact(int sock_fd, void *buffer, size_t num_bytes) {
    size_t total = 0;
    char *ptr = (char *)buffer;
    while (total < num_bytes) {
        ssize_t n = recv(sock_fd, ptr + total, num_bytes - total, 0);
        if (n <= 0) {
            return -1; // Kết nối bị đóng hoặc lỗi
        }
        total += n;
    }
    return 0; // Thành công
}

// Gửi thông điệp nhị phân chuẩn MessageHeader + Payload
static int send_message(int sock_fd, uint8_t msg_type, uint8_t status, const void *payload, uint32_t payload_len) {
    MessageHeader hdr;
    hdr.magic = htons(SYNC_MAGIC);
    hdr.msg_type = msg_type;
    hdr.status = status;
    hdr.payload_len = htonl(payload_len);

    if (send(sock_fd, &hdr, sizeof(MessageHeader), 0) < 0) {
        return -1;
    }
    if (payload_len > 0 && payload != NULL) {
        if (send(sock_fd, payload, payload_len, 0) < 0) {
            return -1;
        }
    }
    return 0;
}

// Xử lý khi nhận được gói tọa độ CMD_WAYPOINT (0x04)
static void handle_cmd_waypoint(int client_fd, const uint8_t *payload, uint32_t payload_len) {
    if (payload_len < 2) {
        printf(COLOR_RED "[SERVER] Lỗi: Gói CMD_WAYPOINT quá ngắn (%u bytes)!\n" COLOR_RESET, payload_len);
        return;
    }

    uint16_t count = 0;
    memcpy(&count, payload, sizeof(uint16_t));
    count = ntohs(count);

    if (count > MAX_WAYPOINTS) {
        printf(COLOR_RED "[SERVER] Lỗi: Số lượng waypoint không hợp lệ (%u > %d)!\n" COLOR_RESET, count, MAX_WAYPOINTS);
        return;
    }

    size_t expected_min = 2 + count * sizeof(WaypointItem);
    if (payload_len < expected_min) {
        printf(COLOR_RED "[SERVER] Lỗi: Không đủ dữ liệu cho %u waypoints (cần %zu, có %u)!\n" COLOR_RESET,
               count, expected_min, payload_len);
        return;
    }

    printf("\n" COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(COLOR_GREEN "  🎯 [SERVER] NHẬN ĐƯỢC LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT - 0x04)" COLOR_RESET "\n");
    printf(COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(" * Socket Client FD       : %d\n", client_fd);
    printf(" * Tổng số điểm tọa độ    : " COLOR_YELLOW "%u điểm" COLOR_RESET "\n", count);
    printf(" * Độ dài Payload         : %u bytes\n", payload_len);
    printf("--------------------------------------------------------------------\n");

    const WaypointItem *items = (const WaypointItem *)(payload + 2);
    for (uint16_t i = 0; i < count; i++) {
        float lat = ntohf(items[i].latitude);
        float lon = ntohf(items[i].longitude);
        float alt = ntohf(items[i].altitude);
        float speed = ntohf(items[i].speed);

        // Quy đổi ra khoảng cách centimet (cm) so với trạm gốc HOME (0, 0)
        float dx_cm = lon * 100000.0f * 100.0f;
        float dy_cm = lat * 100000.0f * 100.0f;

        printf("  [" COLOR_YELLOW "Điểm %02u" COLOR_RESET "] Vĩ độ: " COLOR_GREEN "%+10.6f" COLOR_RESET 
               " | Kinh độ: " COLOR_GREEN "%+10.6f" COLOR_RESET 
               " | Độ cao: " COLOR_CYAN "%5.1fm" COLOR_RESET 
               " | Tốc độ: %4.1fm/s\n",
               i + 1, lat, lon, alt, speed);
        printf("           -> Tọa độ Radar: X = " COLOR_MAGENTA "%+7.1f cm" COLOR_RESET 
               ", Y = " COLOR_MAGENTA "%+7.1f cm" COLOR_RESET "\n", dx_cm, dy_cm);
    }
    printf(COLOR_CYAN "====================================================================\n" COLOR_RESET);

    // Gửi phản hồi PONG hoặc giữ trạng thái xác nhận tới Client
    send_message(client_fd, OP_PONG, 0, NULL, 0);
}

// Xử lý khi Client là trình duyệt Web gửi HTTP request
static bool try_handle_http_request(int client_fd, const char *req, size_t len) {
    if (len < 4) return false;
    if (strncmp(req, "GET ", 4) != 0 && strncmp(req, "POST", 4) != 0) {
        return false;
    }

    // Nếu là POST gửi tọa độ từ Web Client (/api/waypoint hoặc /coordinate)
    if (strstr(req, "POST /api/waypoint") || strstr(req, "POST /coordinate")) {
        char *body = strstr(req, "\r\n\r\n");
        if (body) {
            body += 4;
            float lat = 0.0f, lon = 0.0f, alt = 10.0f, speed = 1.0f;
            char *p_lat = strstr(body, "\"lat\"");
            char *p_lon = strstr(body, "\"lon\"");
            char *p_alt = strstr(body, "\"alt\"");
            char *p_spd = strstr(body, "\"speed\"");

            if (p_lat) sscanf(p_lat, "\"lat\"%*[^0-9+-]%f", &lat);
            if (p_lon) sscanf(p_lon, "\"lon\"%*[^0-9+-]%f", &lon);
            if (p_alt) sscanf(p_alt, "\"alt\"%*[^0-9+-]%f", &alt);
            if (p_spd) sscanf(p_spd, "\"speed\"%*[^0-9+-]%f", &speed);

            printf("\n" COLOR_CYAN "====================================================================" COLOR_RESET "\n");
            printf(COLOR_GREEN "  🌐 [SERVER] NHẬN TỌA ĐỘ TỪ WEB CLIENT (HTTP/JSON)" COLOR_RESET "\n");
            printf(COLOR_CYAN "====================================================================" COLOR_RESET "\n");
            printf("  -> Tọa độ: Vĩ độ = " COLOR_GREEN "%.6f" COLOR_RESET ", Kinh độ = " COLOR_GREEN "%.6f" COLOR_RESET "\n", lat, lon);
            printf("  -> Độ cao: " COLOR_CYAN "%.1fm" COLOR_RESET " | Vận tốc: %.1fm/s\n", alt, speed);
            printf("  -> Khoảng cách Radar: X = %+.1f cm, Y = %+.1f cm\n", lon * 10000000.0f, lat * 10000000.0f);
            printf(COLOR_CYAN "====================================================================\n" COLOR_RESET);

            const char *resp = "HTTP/1.1 200 OK\r\n"
                               "Content-Type: application/json\r\n"
                               "Access-Control-Allow-Origin: *\r\n"
                               "Content-Length: 27\r\n\r\n"
                               "{\"status\":\"ok\",\"code\":0}";
            send(client_fd, resp, strlen(resp), 0);
            return true;
        }
    }

    // Nếu là GET /, trả về giao diện Web Client tương tác
    if (strstr(req, "GET /")) {
        const char *html = 
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>UAV Web Client</title>"
            "<style>body{font-family:Arial,sans-serif;margin:30px;background:#1a1a2e;color:#e94560}"
            ".card{background:#16213e;padding:25px;border-radius:12px;max-width:500px;margin:auto;box-shadow:0 4px 15px rgba(0,0,0,0.5)}"
            "input{width:90%;padding:10px;margin:8px 0;background:#0f3460;border:1px solid #e94560;color:#fff;border-radius:6px}"
            "button{background:#e94560;color:#fff;padding:12px 20px;border:none;border-radius:6px;cursor:pointer;font-weight:bold;width:96%;margin-top:15px}"
            "button:hover{background:#ff5470}#log{margin-top:15px;color:#4ecca3;font-size:14px}</style></head>"
            "<body><div class='card'><h2>🚁 UAV Survey - Gửi Tọa Độ</h2>"
            "<label>Vĩ độ (Latitude):</label><input id='lat' value='0.000100'>"
            "<label>Kinh độ (Longitude):</label><input id='lon' value='0.000150'>"
            "<label>Độ cao (Altitude - m):</label><input id='alt' value='15.0'>"
            "<label>Vận tốc (Speed - m/s):</label><input id='spd' value='1.0'>"
            "<button onclick='sendCoord()'>GỬI TỌA ĐỘ TỚI SERVER</button><div id='log'></div>"
            "</div><script>"
            "function sendCoord(){"
            "fetch('/api/waypoint',{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value),alt:parseFloat(document.getElementById('alt').value),speed:parseFloat(document.getElementById('spd').value)})})"
            ".then(r=>r.json()).then(d=>document.getElementById('log').innerText='[OK] Server đã nhận tọa độ!')"
            ".catch(e=>document.getElementById('log').innerText='[Lỗi] '+e);"
            "}</script></body></html>";
        send(client_fd, html, strlen(html), 0);
        return true;
    }

    return false;
}

// Luồng xử lý riêng cho từng Client kết nối
typedef struct {
    int client_fd;
    struct sockaddr_in client_addr;
} ClientThreadArgs;

static void *client_worker_thread(void *arg) {
    ClientThreadArgs *args = (ClientThreadArgs *)arg;
    int client_fd = args->client_fd;
    char client_ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &args->client_addr.sin_addr, client_ip, sizeof(client_ip));
    int client_port = ntohs(args->client_addr.sin_port);
    free(args);

    printf(COLOR_GREEN "[SERVER] Chấp nhận kết nối TCP từ %s:%d (Socket FD: %d)\n" COLOR_RESET,
           client_ip, client_port, client_fd);

    bool is_authenticated = false;
    uint8_t payload_buffer[BUFFER_SIZE];

    while (1) {
        // Đọc 8 bytes Header
        MessageHeader hdr;
        int ret = recv(client_fd, &hdr, sizeof(MessageHeader), MSG_PEEK);
        if (ret <= 0) {
            break; // Ngắt kết nối
        }

        // Kiểm tra xem có phải Client Web gửi HTTP request không
        if (ret >= 4 && (memcmp(&hdr, "GET ", 4) == 0 || memcmp(&hdr, "POST", 4) == 0)) {
            char http_buf[BUFFER_SIZE];
            ssize_t hlen = recv(client_fd, http_buf, sizeof(http_buf) - 1, 0);
            if (hlen > 0) {
                http_buf[hlen] = '\0';
                try_handle_http_request(client_fd, http_buf, hlen);
            }
            break;
        }

        // Nếu là gói tin nhị phân chuẩn giaothuc.pdf
        if (recv_exact(client_fd, &hdr, sizeof(MessageHeader)) != 0) {
            break;
        }

        uint16_t magic = ntohs(hdr.magic);
        uint8_t msg_type = hdr.msg_type;
        uint32_t payload_len = ntohl(hdr.payload_len);

        if (magic != SYNC_MAGIC) {
            printf(COLOR_RED "[SERVER] Gói tin sai Magic (0x%04X != 0x%04X), ngắt kết nối!\n" COLOR_RESET,
                   magic, SYNC_MAGIC);
            break;
        }

        // Đọc payload nếu có
        if (payload_len > 0) {
            if (payload_len > sizeof(payload_buffer)) {
                printf(COLOR_RED "[SERVER] Payload quá lớn (%u bytes), ngắt kết nối!\n" COLOR_RESET, payload_len);
                break;
            }
            if (recv_exact(client_fd, payload_buffer, payload_len) != 0) {
                printf(COLOR_RED "[SERVER] Lỗi đọc Payload (%u bytes)\n" COLOR_RESET, payload_len);
                break;
            }
        }

        // 1. Xử lý AUTH_REQ (0x01)
        if (msg_type == OP_AUTH_REQ) {
            if (payload_len == sizeof(AuthReqPayload)) {
                AuthReqPayload *req = (AuthReqPayload *)payload_buffer;
                char dev_id[17] = {0};
                char sec_key[33] = {0};
                strncpy(dev_id, req->device_id, 16);
                strncpy(sec_key, req->secret_key, 32);

                printf(COLOR_CYAN "[SERVER] Nhận AUTH_REQ (0x01): Device='%s', Key='%s'\n" COLOR_RESET, dev_id, sec_key);

                // Xác thực đơn giản: Chấp nhận mọi thiết bị có key hợp lệ
                is_authenticated = (strlen(sec_key) > 0 && strcmp(sec_key, "wrong") != 0);

                AuthResPayload res;
                res.status_code = is_authenticated ? 0 : 1;
                strncpy(res.session_token, is_authenticated ? "TOK_UAV_SURVEY_2026_OK" : "", 32);

                send_message(client_fd, OP_AUTH_RES, res.status_code, &res, sizeof(res));
                if (is_authenticated) {
                    printf(COLOR_GREEN "[SERVER] -> Xác thực THÀNH CÔNG cho '%s'!\n" COLOR_RESET, dev_id);
                } else {
                    printf(COLOR_RED "[SERVER] -> Xác thực THẤT BẠI cho '%s'!\n" COLOR_RESET, dev_id);
                    break;
                }
            }
        }
        // 2. Xử lý CMD_WAYPOINT (0x04) - LỆNH GỬI TỌA ĐỘ
        else if (msg_type == OP_CMD_WAYPOINT) {
            if (!is_authenticated) {
                printf(COLOR_YELLOW "[SERVER] Cảnh báo: Nhận tọa độ khi chưa xác thực, vẫn chấp nhận xử lý!\n" COLOR_RESET);
            }
            handle_cmd_waypoint(client_fd, payload_buffer, payload_len);
        }
        // 3. Xử lý CMD_ACTION (0x05)
        else if (msg_type == OP_CMD_ACTION) {
            if (payload_len >= sizeof(CmdActionPayload)) {
                CmdActionPayload *act = (CmdActionPayload *)payload_buffer;
                printf(COLOR_YELLOW "[SERVER] Nhận lệnh CMD_ACTION (0x05): ActionType = %u " COLOR_RESET, act->action_type);
                if (act->action_type == ACTION_TAKEOFF) printf("(TAKEOFF - Cất cánh)\n");
                else if (act->action_type == ACTION_LAND) printf("(LAND - Hạ cánh)\n");
                else if (act->action_type == ACTION_RTL) printf("(RTL - Về trạm)\n");
                else printf("(Không xác định)\n");
            }
        }
        // 4. Xử lý PING (0x0A) -> Trả về PONG (0x0B)
        else if (msg_type == OP_PING) {
            send_message(client_fd, OP_PONG, 0, NULL, 0);
        }
        // 5. Xử lý PONG (0x0B)
        else if (msg_type == OP_PONG) {
            // Nhịp tim bình thường
        }
        else {
            printf(COLOR_YELLOW "[SERVER] Nhận msg_type lạ: 0x%02X\n" COLOR_RESET, msg_type);
        }
    }

    printf(COLOR_YELLOW "[SERVER] Client %s:%d đã ngắt kết nối (Socket FD: %d)\n" COLOR_RESET,
           client_ip, client_port, client_fd);
    close(client_fd);
    return NULL;
}

// Khởi tạo máy chủ TCP
bool tcp_server_init(TcpServer *server, int port) {
    if (!server) return false;
    memset(server, 0, sizeof(TcpServer));
    server->port = (port > 0) ? port : 8080;

    server->listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server->listen_fd < 0) {
        perror("socket");
        return false;
    }

    int opt = 1;
    setsockopt(server->listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in srv_addr;
    memset(&srv_addr, 0, sizeof(srv_addr));
    srv_addr.sin_family = AF_INET;
    srv_addr.sin_addr.s_addr = INADDR_ANY;
    srv_addr.sin_port = htons(server->port);

    if (bind(server->listen_fd, (struct sockaddr *)&srv_addr, sizeof(srv_addr)) < 0) {
        perror("bind");
        close(server->listen_fd);
        return false;
    }

    if (listen(server->listen_fd, 10) < 0) {
        perror("listen");
        close(server->listen_fd);
        return false;
    }

    server->running = true;
    return true;
}

// Vòng lặp lắng nghe kết nối
void tcp_server_run(TcpServer *server) {
    if (!server || !server->running) return;

    printf("\n" COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(COLOR_GREEN "  🚁 UAV SURVEY NET - TCP SERVER ĐÃ KHỞI ĐỘNG THÀNH CÔNG!" COLOR_RESET "\n");
    printf(COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(" * Cổng TCP lắng nghe   : " COLOR_YELLOW "%d" COLOR_RESET "\n", server->port);
    printf(" * Chữ ký đồng bộ Magic : " COLOR_YELLOW "0x%04X" COLOR_RESET " (2 bytes Big-Endian)\n", SYNC_MAGIC);
    printf(" * Giao thức hỗ trợ     : Nhận tọa độ " COLOR_GREEN "CMD_WAYPOINT (0x04)" COLOR_RESET " + Web HTTP\n");
    printf(" * Sẵn sàng đón kết nối từ Client GUI / Web Client...\n");
    printf(COLOR_CYAN "====================================================================\n" COLOR_RESET);

    while (server->running) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        int client_fd = accept(server->listen_fd, (struct sockaddr *)&client_addr, &addr_len);

        if (client_fd < 0) {
            if (!server->running) break;
            perror("accept");
            continue;
        }

        ClientThreadArgs *args = (ClientThreadArgs *)malloc(sizeof(ClientThreadArgs));
        if (!args) {
            close(client_fd);
            continue;
        }
        args->client_fd = client_fd;
        memcpy(&args->client_addr, &client_addr, sizeof(client_addr));

        pthread_t tid;
        if (pthread_create(&tid, NULL, client_worker_thread, args) == 0) {
            pthread_detach(tid);
        } else {
            close(client_fd);
            free(args);
        }
    }
}

// Dừng máy chủ
void tcp_server_stop(TcpServer *server) {
    if (!server) return;
    server->running = false;
    if (server->listen_fd >= 0) {
        shutdown(server->listen_fd, SHUT_RDWR);
        close(server->listen_fd);
        server->listen_fd = -1;
    }
    printf(COLOR_YELLOW "[SERVER] Máy chủ TCP đã dừng.\n" COLOR_RESET);
}

