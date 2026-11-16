#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include "tcp_server.h"

static TcpServer g_server;

static void handle_signal(int sig) {
    (void)sig;
    printf("\n[SERVER] Đang dừng máy chủ an toàn...\n");
    tcp_server_stop(&g_server);
    exit(0);
}

int main(int argc, char *argv[]) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGPIPE, SIG_IGN);

    int tcp_port = DEFAULT_TCP_PORT; // 8080
    int udp_port = DEFAULT_UDP_PORT; // 8081

    if (argc > 1) {
        tcp_port = atoi(argv[1]);
        if (tcp_port <= 0 || tcp_port > 65535) tcp_port = DEFAULT_TCP_PORT;
    }
    if (argc > 2) {
        udp_port = atoi(argv[2]);
        if (udp_port <= 0 || udp_port > 65535) udp_port = DEFAULT_UDP_PORT;
    }

    if (!tcp_server_init(&g_server, tcp_port, udp_port)) {
        fprintf(stderr, "Không thể khởi tạo máy chủ trên TCP:%d và UDP:%d!\n", tcp_port, udp_port);
        return 1;
    }

    tcp_server_run(&g_server);
    return 0;
}
