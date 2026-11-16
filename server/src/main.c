#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include "tcp_server.h"

static TcpServer g_server;

static void handle_signal(int sig) {
    (void)sig;
    printf("\n[SERVER] Nhận tín hiệu dừng (SIGINT/SIGTERM), đang đóng máy chủ...\n");
    tcp_server_stop(&g_server);
    exit(0);
}

int main(int argc, char *argv[]) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGPIPE, SIG_IGN); // Bỏ qua SIGPIPE nếu client đột ngột ngắt kết nối

    int port = 8080;
    if (argc > 1) {
        port = atoi(argv[1]);
        if (port <= 0 || port > 65535) {
            fprintf(stderr, "Cổng không hợp lệ: %s. Sử dụng cổng mặc định 8080.\n", argv[1]);
            port = 8080;
        }
    }

    if (!tcp_server_init(&g_server, port)) {
        fprintf(stderr, "Không thể khởi tạo máy chủ TCP trên cổng %d!\n", port);
        return 1;
    }

    // Bắt đầu chạy vòng lặp phục vụ các kết nối TCP
    tcp_server_run(&g_server);

    return 0;
}

