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
#include <time.h>

#define COLOR_RESET   "\033[0m"
#define COLOR_GREEN   "\033[1;32m"
#define COLOR_CYAN    "\033[1;36m"
#define COLOR_YELLOW  "\033[1;33m"
#define COLOR_RED     "\033[1;31m"
#define COLOR_MAGENTA "\033[1;35m"

#define BUFFER_SIZE 2048
#define METERS_PER_DEG 100000.0f // 1 độ = 100,000m

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

int recv_exact(int sock_fd, void *buffer, size_t num_bytes) {
    size_t total = 0;
    char *ptr = (char *)buffer;
    while (total < num_bytes) {
        ssize_t n = recv(sock_fd, ptr + total, num_bytes - total, 0);
        if (n <= 0) {
            return -1;
        }
        total += n;
    }
    return 0;
}

static int send_message(int sock_fd, uint8_t msg_type, uint8_t status, const void *payload, uint32_t payload_len) {
    MessageHeader hdr;
    hdr.magic = htons(SYNC_MAGIC);
    hdr.msg_type = msg_type;
    hdr.status = status;
    hdr.payload_len = htonl(payload_len);

    if (send(sock_fd, &hdr, sizeof(MessageHeader), 0) < 0) return -1;
    if (payload_len > 0 && payload != NULL) {
        if (send(sock_fd, payload, payload_len, 0) < 0) return -1;
    }
    return 0;
}

// ======================================================================
// LUỒNG MÔ PHỎNG VẬT LÝ UAV & PHÁT GÓI TIN UDP TELEMETRY 20Hz (50ms)
// ======================================================================
static void *uav_simulation_thread(void *arg) {
    TcpServer *server = (TcpServer *)arg;
    float dt = 0.05f; // 50ms = 20Hz
    uint32_t packet_count = 0;

    struct timespec start_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);

    printf(COLOR_CYAN "[UDP SIMULATOR] Đã kích hoạt luồng phát Telemetry UDP 20Hz tới cổng %d!\n" COLOR_RESET, server->udp_port);

    while (server->running) {
        usleep(50000); // 50ms

        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        uint32_t elapsed_ms = (uint32_t)((now.tv_sec - start_time.tv_sec) * 1000 + (now.tv_nsec - start_time.tv_nsec) / 1000000);

        UavSimState *u = &server->uav;
        pthread_mutex_lock(&u->lock);

        // 1. Cập nhật Pin
        if (u->alt > 0.5f || u->flight_mode == FLIGHT_MODE_MISSION || u->flight_mode == FLIGHT_MODE_AUTO_RTL) {
            u->battery = fmaxf(5.0f, u->battery - 0.02f * dt);
        }

        // 2. Nội suy độ cao (Altitude)
        float alt_diff = u->target_alt - u->alt;
        float climb_step = 1.0f * dt; // Tốc độ nâng/hạ 1.0 m/s
        if (fabsf(alt_diff) <= climb_step) {
            u->alt = u->target_alt;
        } else {
            u->alt += (alt_diff > 0 ? climb_step : -climb_step);
        }

        if (u->target_alt == 0.0f && u->alt <= 0.02f && u->waypoint_count == 0) {
            u->alt = 0.0f;
            u->speed = 0.0f;
            u->pitch = 0.0f;
            u->roll = 0.0f;
            if (u->flight_mode != FLIGHT_MODE_IDLE) {
                u->flight_mode = FLIGHT_MODE_LANDED;
            }
        }

        // 3. Nội suy vị trí ngang theo Waypoint
        if (u->current_wp_index < u->waypoint_count) {
            WaypointItem *wp = &u->active_waypoints[u->current_wp_index];
            u->target_alt = wp->altitude;

            float dx_m = (wp->longitude - u->lon) * METERS_PER_DEG;
            float dy_m = (wp->latitude - u->lat) * METERS_PER_DEG;
            float dist_m = hypotf(dx_m, dy_m);

            float fly_speed = fmaxf(0.5f, wp->speed);
            float step_m = fly_speed * dt;

            if (dist_m <= step_m || dist_m < 0.01f) {
                // Đã tới điểm này
                u->lat = wp->latitude;
                u->lon = wp->longitude;
                u->current_wp_index++;
                if (u->current_wp_index >= u->waypoint_count) {
                    u->waypoint_count = 0;
                    u->current_wp_index = 0;
                    u->speed = 0.0f;
                    u->pitch = 0.0f;
                    u->roll = 0.0f;
                    if (u->flight_mode == FLIGHT_MODE_AUTO_RTL) {
                        u->target_alt = 0.0f; // Hạ cánh khi về tới HOME
                    }
                }
            } else {
                float heading = atan2f(dx_m, dy_m) * 180.0f / (float)M_PI;
                if (heading < 0) heading += 360.0f;
                u->yaw = heading;
                u->speed = fly_speed;
                u->pitch = -4.0f;
                u->roll = 1.2f * sinf(elapsed_ms / 300.0f);

                u->lon += (dx_m / dist_m * step_m) / METERS_PER_DEG;
                u->lat += (dy_m / dist_m * step_m) / METERS_PER_DEG;
            }
        } else {
            u->speed = fabsf(alt_diff) > 0.01f ? fabsf(alt_diff) / dt : 0.0f;
            u->pitch = 0.0f;
            u->roll = 0.0f;
        }

        // Đóng gói TelemetryPayload (34 bytes)
        TelemetryPayload telem;
        telem.timestamp_ms = htonl(elapsed_ms);
        telem.latitude = htonf(u->lat);
        telem.longitude = htonf(u->lon);
        telem.altitude = htonf(u->alt);
        telem.roll = htonf(u->roll);
        telem.pitch = htonf(u->pitch);
        telem.yaw = htonf(u->yaw);
        telem.speed = htonf(u->speed);
        telem.battery = (uint8_t)roundf(u->battery);
        telem.flight_mode = u->flight_mode;

        float curr_lat = u->lat;
        float curr_lon = u->lon;
        float curr_alt = u->alt;
        float curr_spd = u->speed;
        uint8_t curr_bat = telem.battery;
        uint8_t curr_mode = u->flight_mode;

        pthread_mutex_unlock(&u->lock);

        // Đóng gói hoàn chỉnh [Header 8B + Payload 34B = 42B]
        uint8_t udp_packet[sizeof(MessageHeader) + sizeof(TelemetryPayload)];
        MessageHeader *hdr = (MessageHeader *)udp_packet;
        hdr->magic = htons(SYNC_MAGIC);
        hdr->msg_type = OP_TELEMETRY;
        hdr->status = 0;
        hdr->payload_len = htonl(sizeof(TelemetryPayload));
        memcpy(udp_packet + sizeof(MessageHeader), &telem, sizeof(TelemetryPayload));

        // Bắn gói UDP tới Client kết nối và phát broadcast nội bộ
        pthread_mutex_lock(&server->client_lock);
        if (server->has_client) {
            sendto(server->udp_fd, udp_packet, sizeof(udp_packet), 0,
                   (struct sockaddr *)&server->client_udp_addr, sizeof(server->client_udp_addr));
        }
        pthread_mutex_unlock(&server->client_lock);

        // Luôn phát tới 127.0.0.1:8081 để phục vụ Client GUI chạy trên cùng máy
        struct sockaddr_in local_addr;
        memset(&local_addr, 0, sizeof(local_addr));
        local_addr.sin_family = AF_INET;
        local_addr.sin_port = htons(server->udp_port);
        inet_pton(AF_INET, "127.0.0.1", &local_addr.sin_addr);
        sendto(server->udp_fd, udp_packet, sizeof(udp_packet), 0,
               (struct sockaddr *)&local_addr, sizeof(local_addr));

        packet_count++;
        // In log định kỳ (100 gói = 5 giây một lần) để không spam console
        if (packet_count % 100 == 1) {
            float dx_cm = curr_lon * METERS_PER_DEG * 100.0f;
            float dy_cm = curr_lat * METERS_PER_DEG * 100.0f;
            printf(COLOR_CYAN "[UDP 20Hz #%05u]" COLOR_RESET 
                   " Pos:(%+8.5f, %+8.5f) -> Radar:[X=%+6.0fcm, Y=%+6.0fcm] | Cao:%4.1fm | Spd:%3.1fm/s | Pin:%3u%% | Mode:%u\n",
                   packet_count, curr_lat, curr_lon, dx_cm, dy_cm, curr_alt, curr_spd, curr_bat, curr_mode);
        }
    }

    return NULL;
}

// ======================================================================
// XỬ LÝ LỆNH GỬI TỌA ĐỘ CMD_WAYPOINT (0x04)
// ======================================================================
static void handle_cmd_waypoint(TcpServer *server, int client_fd, const uint8_t *payload, uint32_t payload_len) {
    if (payload_len < 2) return;

    uint16_t count = 0;
    memcpy(&count, payload, sizeof(uint16_t));
    count = ntohs(count);

    if (count > MAX_WAYPOINTS) return;

    printf("\n" COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(COLOR_GREEN "  🎯 [SERVER] TIẾP NHẬN LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT - 0x04)!" COLOR_RESET "\n");
    printf(COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(" * Tổng số điểm tọa độ: " COLOR_YELLOW "%u điểm" COLOR_RESET " (Gói tin: %u bytes)\n", count, payload_len + 8);
    printf("--------------------------------------------------------------------\n");

    const WaypointItem *items = (const WaypointItem *)(payload + 2);

    pthread_mutex_lock(&server->uav.lock);
    server->uav.waypoint_count = count;
    server->uav.current_wp_index = 0;
    server->uav.flight_mode = FLIGHT_MODE_MISSION;

    for (uint16_t i = 0; i < count; i++) {
        float lat = ntohf(items[i].latitude);
        float lon = ntohf(items[i].longitude);
        float alt = ntohf(items[i].altitude);
        float speed = ntohf(items[i].speed);

        server->uav.active_waypoints[i].latitude = lat;
        server->uav.active_waypoints[i].longitude = lon;
        server->uav.active_waypoints[i].altitude = alt;
        server->uav.active_waypoints[i].speed = speed;

        float dx_cm = lon * METERS_PER_DEG * 100.0f;
        float dy_cm = lat * METERS_PER_DEG * 100.0f;

        printf("  [" COLOR_YELLOW "Điểm %02u" COLOR_RESET "] Lat: " COLOR_GREEN "%+10.6f" COLOR_RESET 
               " | Lon: " COLOR_GREEN "%+10.6f" COLOR_RESET 
               " | Cao: " COLOR_CYAN "%5.1fm" COLOR_RESET 
               " | Tốc độ: %4.1fm/s\n",
               i + 1, lat, lon, alt, speed);
        printf("           -> Tọa độ Radar: X = " COLOR_MAGENTA "%+7.1f cm" COLOR_RESET 
               ", Y = " COLOR_MAGENTA "%+7.1f cm" COLOR_RESET "\n", dx_cm, dy_cm);
    }

    if (count > 0 && server->uav.alt < 1.0f) {
        server->uav.target_alt = fmaxf(1.0f, server->uav.active_waypoints[0].altitude);
        printf(COLOR_YELLOW "  -> UAV tự động cất cánh nâng độ cao lên %.1fm để bắt đầu bay!\n" COLOR_RESET, server->uav.target_alt);
    }

    pthread_mutex_unlock(&server->uav.lock);
    printf(COLOR_CYAN "====================================================================\n" COLOR_RESET);

    // Gửi phản hồi PONG xác nhận
    send_message(client_fd, OP_PONG, 0, NULL, 0);
}

// Xử lý lệnh can thiệp tức thời CMD_ACTION (0x05)
static void handle_cmd_action(TcpServer *server, uint8_t action_type) {
    pthread_mutex_lock(&server->uav.lock);
    if (action_type == ACTION_TAKEOFF) {
        server->uav.flight_mode = FLIGHT_MODE_MISSION;
        server->uav.target_alt = fmaxf(1.5f, server->uav.alt);
        printf(COLOR_GREEN "[SERVER] Lệnh TAKEOFF -> Cất cánh lên độ cao %.1fm!\n" COLOR_RESET, server->uav.target_alt);
    } else if (action_type == ACTION_LAND) {
        server->uav.waypoint_count = 0;
        server->uav.current_wp_index = 0;
        server->uav.target_alt = 0.0f;
        printf(COLOR_YELLOW "[SERVER] Lệnh LAND -> Đang hạ cánh khẩn cấp tại chỗ!\n" COLOR_RESET);
    } else if (action_type == ACTION_RTL) {
        server->uav.flight_mode = FLIGHT_MODE_AUTO_RTL;
        server->uav.waypoint_count = 1;
        server->uav.current_wp_index = 0;
        server->uav.active_waypoints[0].latitude = 0.0f;
        server->uav.active_waypoints[0].longitude = 0.0f;
        server->uav.active_waypoints[0].altitude = fmaxf(1.5f, server->uav.alt);
        server->uav.active_waypoints[0].speed = 1.0f;
        printf(COLOR_MAGENTA "[SERVER] Lệnh RTL -> Kích hoạt Auto RTL bay về trạm gốc HOME (0,0)!\n" COLOR_RESET);
    }
    pthread_mutex_unlock(&server->uav.lock);
}

// Hỗ trợ Web Client qua HTTP (khi truy cập bằng trình duyệt)
static bool try_handle_http(TcpServer *server, int client_fd, const char *req, size_t len) {
    if (len < 4) return false;
    if (strncmp(req, "GET ", 4) != 0 && strncmp(req, "POST", 4) != 0) return false;

    // API lấy Telemetry thời gian thực cho Web Client
    if (strstr(req, "GET /api/telemetry")) {
        pthread_mutex_lock(&server->uav.lock);
        char json[512];
        float dx_cm = server->uav.lon * METERS_PER_DEG * 100.0f;
        float dy_cm = server->uav.lat * METERS_PER_DEG * 100.0f;
        snprintf(json, sizeof(json),
            "{\"lat\":%.6f,\"lon\":%.6f,\"alt\":%.2f,\"speed\":%.2f,\"yaw\":%.1f,\"battery\":%.0f,\"mode\":%u,\"dx_cm\":%.1f,\"dy_cm\":%.1f}",
            server->uav.lat, server->uav.lon, server->uav.alt, server->uav.speed, server->uav.yaw,
            server->uav.battery, server->uav.flight_mode, dx_cm, dy_cm);
        pthread_mutex_unlock(&server->uav.lock);

        char resp[1024];
        snprintf(resp, sizeof(resp),
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: %zu\r\n\r\n%s",
            strlen(json), json);
        send(client_fd, resp, strlen(resp), 0);
        return true;
    }

    // API nhận Tọa độ từ Web Client
    if (strstr(req, "POST /api/waypoint") || strstr(req, "POST /coordinate")) {
        char *body = strstr(req, "\r\n\r\n");
        if (body) {
            body += 4;
            float lat = 0.0f, lon = 0.0f, alt = 15.0f, spd = 1.2f;
            char *p_lat = strstr(body, "\"lat\"");
            char *p_lon = strstr(body, "\"lon\"");
            char *p_alt = strstr(body, "\"alt\"");
            char *p_spd = strstr(body, "\"speed\"");

            if (p_lat) sscanf(p_lat, "\"lat\"%*[^0-9+-]%f", &lat);
            if (p_lon) sscanf(p_lon, "\"lon\"%*[^0-9+-]%f", &lon);
            if (p_alt) sscanf(p_alt, "\"alt\"%*[^0-9+-]%f", &alt);
            if (p_spd) sscanf(p_spd, "\"speed\"%*[^0-9+-]%f", &spd);

            // Nạp waypoint vào UAV
            pthread_mutex_lock(&server->uav.lock);
            server->uav.waypoint_count = 1;
            server->uav.current_wp_index = 0;
            server->uav.flight_mode = FLIGHT_MODE_MISSION;
            server->uav.active_waypoints[0].latitude = lat;
            server->uav.active_waypoints[0].longitude = lon;
            server->uav.active_waypoints[0].altitude = alt;
            server->uav.active_waypoints[0].speed = spd;
            if (server->uav.alt < 1.0f) server->uav.target_alt = alt;
            pthread_mutex_unlock(&server->uav.lock);

            printf("\n" COLOR_GREEN "  🌐 [SERVER] NHẬN TỌA ĐỘ TỪ WEB CLIENT (HTTP/JSON): Lat=%.6f, Lon=%.6f, Alt=%.1fm\n" COLOR_RESET, lat, lon, alt);

            const char *resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: 27\r\n\r\n{\"status\":\"ok\",\"code\":0}";
            send(client_fd, resp, strlen(resp), 0);
            return true;
        }
    }

    // Trang Web Client giao diện trực quan
    if (strstr(req, "GET /")) {
        FILE *f = fopen("web/web_client.html", "r");
        if (!f) f = fopen("uav-survey-net/server/web/web_client.html", "r");
        if (f) {
            fseek(f, 0, SEEK_END);
            long fsize = ftell(f);
            fseek(f, 0, SEEK_SET);
            char *html = (char *)malloc(fsize + 1);
            if (html && fread(html, 1, fsize, f) == (size_t)fsize) {
                html[fsize] = '\0';
                char hdr[256];
                snprintf(hdr, sizeof(hdr), "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: %ld\r\n\r\n", fsize);
                send(client_fd, hdr, strlen(hdr), 0);
                send(client_fd, html, fsize, 0);
                free(html);
                fclose(f);
                return true;
            }
            if (html) free(html);
            fclose(f);
        }
    }

    return false;
}

// Xử lý Client kết nối TCP
typedef struct {
    TcpServer *server;
    int client_fd;
    struct sockaddr_in client_addr;
} ClientArgs;

static void *client_worker_thread(void *arg) {
    ClientArgs *args = (ClientArgs *)arg;
    TcpServer *server = args->server;
    int client_fd = args->client_fd;
    char client_ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &args->client_addr.sin_addr, client_ip, sizeof(client_ip));
    int client_port = ntohs(args->client_addr.sin_port);

    printf(COLOR_GREEN "[SERVER] Chấp nhận kết nối TCP từ %s:%d\n" COLOR_RESET, client_ip, client_port);

    // Ghi nhận địa chỉ UDP của Client để phát Telemetry
    pthread_mutex_lock(&server->client_lock);
    server->client_udp_addr = args->client_addr;
    server->client_udp_addr.sin_port = htons(server->udp_port); // Cổng 8081
    server->has_client = true;
    pthread_mutex_unlock(&server->client_lock);

    free(args);

    uint8_t payload_buffer[BUFFER_SIZE];

    while (server->running) {
        MessageHeader hdr;
        int ret = recv(client_fd, &hdr, sizeof(MessageHeader), MSG_PEEK);
        if (ret <= 0) break;

        if (ret >= 4 && (memcmp(&hdr, "GET ", 4) == 0 || memcmp(&hdr, "POST", 4) == 0)) {
            char http_buf[BUFFER_SIZE];
            ssize_t hlen = recv(client_fd, http_buf, sizeof(http_buf) - 1, 0);
            if (hlen > 0) {
                http_buf[hlen] = '\0';
                try_handle_http(server, client_fd, http_buf, hlen);
            }
            break;
        }

        if (recv_exact(client_fd, &hdr, sizeof(MessageHeader)) != 0) break;

        uint16_t magic = ntohs(hdr.magic);
        uint8_t msg_type = hdr.msg_type;
        uint32_t payload_len = ntohl(hdr.payload_len);

        if (magic != SYNC_MAGIC) {
            printf(COLOR_RED "[SERVER] Gói tin sai Magic (0x%04X != 0x%04X)!\n" COLOR_RESET, magic, SYNC_MAGIC);
            break;
        }

        if (payload_len > 0) {
            if (payload_len > sizeof(payload_buffer)) break;
            if (recv_exact(client_fd, payload_buffer, payload_len) != 0) break;
        }

        if (msg_type == OP_AUTH_REQ) {
            AuthReqPayload *req = (AuthReqPayload *)payload_buffer;
            char dev_id[17] = {0};
            strncpy(dev_id, req->device_id, 16);
            printf(COLOR_CYAN "[SERVER] Xác thực AUTH_REQ cho thiết bị '%s' -> Thành công!\n" COLOR_RESET, dev_id);

            AuthResPayload res = { .status_code = 0 };
            strncpy(res.session_token, "TOK_UAV_SURVEY_2026_OK", 32);
            send_message(client_fd, OP_AUTH_RES, 0, &res, sizeof(res));
        }
        else if (msg_type == OP_CMD_WAYPOINT) {
            handle_cmd_waypoint(server, client_fd, payload_buffer, payload_len);
        }
        else if (msg_type == OP_CMD_ACTION) {
            if (payload_len >= sizeof(CmdActionPayload)) {
                CmdActionPayload *act = (CmdActionPayload *)payload_buffer;
                handle_cmd_action(server, act->action_type);
            }
        }
        else if (msg_type == OP_PING) {
            send_message(client_fd, OP_PONG, 0, NULL, 0);
        }
    }

    printf(COLOR_YELLOW "[SERVER] Client %s:%d đã ngắt kết nối TCP.\n" COLOR_RESET, client_ip, client_port);
    close(client_fd);
    return NULL;
}

// Khởi tạo máy chủ TCP & kênh phát UDP Telemetry
bool tcp_server_init(TcpServer *server, int tcp_port, int udp_port) {
    if (!server) return false;
    memset(server, 0, sizeof(TcpServer));

    server->tcp_port = (tcp_port > 0) ? tcp_port : DEFAULT_TCP_PORT;
    server->udp_port = (udp_port > 0) ? udp_port : DEFAULT_UDP_PORT;

    pthread_mutex_init(&server->client_lock, NULL);
    pthread_mutex_init(&server->uav.lock, NULL);

    // Khởi tạo trạng thái ban đầu của UAV
    server->uav.lat = 0.0f;
    server->uav.lon = 0.0f;
    server->uav.alt = 0.0f;
    server->uav.battery = 100.0f;
    server->uav.flight_mode = FLIGHT_MODE_IDLE;

    // 1. Tạo socket TCP lắng nghe
    server->tcp_listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server->tcp_listen_fd < 0) return false;

    int opt = 1;
    setsockopt(server->tcp_listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in srv_addr;
    memset(&srv_addr, 0, sizeof(srv_addr));
    srv_addr.sin_family = AF_INET;
    srv_addr.sin_addr.s_addr = INADDR_ANY;
    srv_addr.sin_port = htons(server->tcp_port);

    if (bind(server->tcp_listen_fd, (struct sockaddr *)&srv_addr, sizeof(srv_addr)) < 0) {
        close(server->tcp_listen_fd);
        return false;
    }
    if (listen(server->tcp_listen_fd, 10) < 0) {
        close(server->tcp_listen_fd);
        return false;
    }

    // 2. Tạo socket UDP để phát Telemetry 20Hz
    server->udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (server->udp_fd < 0) {
        close(server->tcp_listen_fd);
        return false;
    }
    int broadcast = 1;
    setsockopt(server->udp_fd, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast));

    server->running = true;

    // Kích hoạt luồng mô phỏng bay và phát gói tin UDP Telemetry 20Hz
    pthread_create(&server->sim_thread, NULL, uav_simulation_thread, server);

    return true;
}

void tcp_server_run(TcpServer *server) {
    if (!server || !server->running) return;

    printf("\n" COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(COLOR_GREEN "  🚁 UAV SURVEY NET - CENTRAL SERVER (TCP & UDP 20Hz SẴN SÀNG!)" COLOR_RESET "\n");
    printf(COLOR_CYAN "====================================================================" COLOR_RESET "\n");
    printf(" * Cổng TCP Lệnh (Command)   : " COLOR_YELLOW "%d" COLOR_RESET " (Nhận CMD_WAYPOINT 0x04)\n", server->tcp_port);
    printf(" * Cổng UDP Telemetry (20Hz) : " COLOR_YELLOW "%d" COLOR_RESET " (Bắn tọa độ về Client)\n", server->udp_port);
    printf(" * Giao thức Magic           : " COLOR_YELLOW "0x%04X" COLOR_RESET " (Big-Endian)\n", SYNC_MAGIC);
    printf(" * Web Client hỗ trợ         : " COLOR_GREEN "http://localhost:%d" COLOR_RESET "\n", server->tcp_port);
    printf(COLOR_CYAN "====================================================================\n" COLOR_RESET);

    while (server->running) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        int client_fd = accept(server->tcp_listen_fd, (struct sockaddr *)&client_addr, &addr_len);
        if (client_fd < 0) {
            if (!server->running) break;
            continue;
        }

        ClientArgs *args = (ClientArgs *)malloc(sizeof(ClientArgs));
        if (args) {
            args->server = server;
            args->client_fd = client_fd;
            args->client_addr = client_addr;
            pthread_t tid;
            if (pthread_create(&tid, NULL, client_worker_thread, args) == 0) {
                pthread_detach(tid);
            } else {
                close(client_fd);
                free(args);
            }
        } else {
            close(client_fd);
        }
    }
}

void tcp_server_stop(TcpServer *server) {
    if (!server) return;
    server->running = false;
    if (server->tcp_listen_fd >= 0) {
        shutdown(server->tcp_listen_fd, SHUT_RDWR);
        close(server->tcp_listen_fd);
        server->tcp_listen_fd = -1;
    }
    if (server->udp_fd >= 0) {
        close(server->udp_fd);
        server->udp_fd = -1;
    }
    pthread_join(server->sim_thread, NULL);
    pthread_mutex_destroy(&server->client_lock);
    pthread_mutex_destroy(&server->uav.lock);
    printf(COLOR_YELLOW "[SERVER] Đã dừng toàn bộ dịch vụ TCP & UDP.\n" COLOR_RESET);
}
