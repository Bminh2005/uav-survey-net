#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_log.h"
#include "esp_tls.h"
#include "uav_auth.h"

#define SERVER_IP "192.168.1.100" // IP Linux Server
#define TCP_PORT "8080"           // Kênh mã hóa TCP[cite: 2]
#define DEVICE_ID "UAV_ESP32_01"
#define SECRET_KEY "MyUavSecretPassphrase2026"

static const char *TAG = "MAIN";

void app_main(void)
{
    // 1. (Giả định Wi-Fi đã được kết nối thành công tại đây)
    esp_tls_cfg_t cfg = {
        .skip_common_name = true,
    };
    // 2. Cấu hình TLS Client[cite: 2]
    esp_tls_t *tls = esp_tls_init();
    if (tls == NULL)
    {
        ESP_LOGE(TAG, "Failed to allocate esp_tls handle!");
        return;
    }
    ESP_LOGI(TAG, "Connecting to TLS Server %s:%d...", SERVER_IP, atoi(TCP_PORT));
    int ret = esp_tls_conn_new_sync(SERVER_IP, strlen(SERVER_IP), atoi(TCP_PORT), &cfg, tls);

    if (ret != 1)
    { // esp_tls_conn_new_sync trả về 1 nếu thành công
        ESP_LOGE(TAG, "TLS Connection failed! Error code: %d", ret);
        esp_tls_conn_destroy(tls);
        return;
    }

    ESP_LOGI(TAG, "TLS Connection established successfully!");
    // 3. Thực hiện xác thực 2 lớp (TLS + Nonce Challenge-Response)[cite: 2, 3]
    if (uav_perform_authentication(tls, DEVICE_ID, SECRET_KEY))
    {
        ESP_LOGI(TAG, "Unlocking UDP Telemetry and Command Listeners...");

        // TODO: Kích hoạt FreeRTOS Task bắn gói UDP Telemetry (Port 8081) 20Hz[cite: 2, 3]
        // TODO: Kích hoạt Watchdog Timer Failsafe 3 giây[cite: 4]
    }
    else
    {
        ESP_LOGE(TAG, "Authentication failed. Closing connection.");
        esp_tls_conn_destroy(tls);
    }
}