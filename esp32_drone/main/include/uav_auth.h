#ifndef UAV_AUTH_H
#define UAV_AUTH_H

#include <stdbool.h>
#include "esp_tls.h"

// Hàm thực hiện toàn bộ luồng handshake xác thực qua kênh TLS TCP[cite: 2]
bool uav_perform_authentication(esp_tls_t *tls, const char *device_id, const char *secret_key);

#endif // UAV_AUTH_H