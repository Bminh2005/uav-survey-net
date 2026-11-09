#include "uav_auth.h"
#include "protocol_defs.h"
#include <string.h>
#include "esp_log.h"
#include "mbedtls/md.h"

static const char *TAG = "UAV_AUTH";

// Hàm tính HMAC-SHA256 bằng thư viện mbedTLS có sẵn trên ESP32
static void compute_hmac_sha256(const uint8_t *key, size_t key_len,
                                const uint8_t *data, size_t data_len,
                                uint8_t *output)
{
    mbedtls_md_context_t ctx;
    mbedtls_md_type_t md_type = MBEDTLS_MD_SHA256;
    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(md_type), 1);
    mbedtls_md_hmac_starts(&ctx, key, key_len);
    mbedtls_md_hmac_update(&ctx, data, data_len);
    mbedtls_md_hmac_finish(&ctx, output);
    mbedtls_md_free(&ctx);
}

bool uav_perform_authentication(esp_tls_t *tls, const char *device_id, const char *secret_key)
{
    MessageHeader hdr;
    int ret;

    // ---------------------------------------------------------------------
    // BƯỚC 1: Gửi gói MSG_AUTH_INIT (Xin Challenge / Nonce)[cite: 3]
    // ---------------------------------------------------------------------
    AuthInitPayload init_payload;
    memset(&init_payload, 0, sizeof(init_payload));
    strncpy(init_payload.device_id, device_id, sizeof(init_payload.device_id) - 1);

    hdr.magic = SYNC_MAGIC;
    hdr.msg_type = MSG_AUTH_INIT;
    hdr.status = 0;
    hdr.payload_len = sizeof(init_payload);

    MessageHeader tx_hdr = hdr;
    header_to_network(&tx_hdr);

    // Gửi Header + Payload qua đường truyền mã hóa TLS TCP[cite: 2]
    esp_tls_conn_write(tls, &tx_hdr, sizeof(tx_hdr));
    esp_tls_conn_write(tls, &init_payload, sizeof(init_payload));
    ESP_LOGI(TAG, "Sent MSG_AUTH_INIT for Device: %s", device_id);

    // ---------------------------------------------------------------------
    // BƯỚC 2: Nhận gói MSG_AUTH_CHALLENGE chứa Nonce từ Server
    // ---------------------------------------------------------------------
    MessageHeader rx_hdr;
    ret = esp_tls_conn_read(tls, &rx_hdr, sizeof(rx_hdr));
    if (ret <= 0)
    {
        ESP_LOGE(TAG, "Failed to receive Auth Challenge Header");
        return false;
    }
    header_to_host(&rx_hdr);
    //[cite:3]

    if (rx_hdr.magic != SYNC_MAGIC || rx_hdr.msg_type != MSG_AUTH_CHALLENGE)
    {
        //[cite:2]
        ESP_LOGE(TAG, "Invalid Auth Challenge response type: 0x%02X", rx_hdr.msg_type);
        return false;
    }

    AuthChallengePayload challenge_payload;
    esp_tls_conn_read(tls, &challenge_payload, sizeof(challenge_payload));
    ESP_LOGI(TAG, "Received Challenge Nonce from Server");

    // ---------------------------------------------------------------------
    // BƯỚC 3: Tính toán HMAC-SHA256 & Gửi MSG_AUTH_REQ[cite: 3]
    // ---------------------------------------------------------------------
    AuthReqPayload req_payload;
    memset(&req_payload, 0, sizeof(req_payload));
    strncpy(req_payload.device_id, device_id, sizeof(req_payload.device_id) - 1);

    // Băm Secret Key + Nonce vừa nhận
    compute_hmac_sha256((const uint8_t *)secret_key, strlen(secret_key),
                        challenge_payload.nonce, sizeof(challenge_payload.nonce),
                        req_payload.response_hash);

    hdr.magic = SYNC_MAGIC;
    hdr.msg_type = MSG_AUTH_REQ;
    hdr.status = 0;
    hdr.payload_len = sizeof(req_payload);

    tx_hdr = hdr;
    header_to_network(&tx_hdr);

    esp_tls_conn_write(tls, &tx_hdr, sizeof(tx_hdr));
    esp_tls_conn_write(tls, &req_payload, sizeof(req_payload));
    ESP_LOGI(TAG, "Sent MSG_AUTH_REQ with HMAC Response");

    // ---------------------------------------------------------------------
    // BƯỚC 4: Nhận kết quả MSG_AUTH_RES từ Server[cite: 3]
    // ---------------------------------------------------------------------
    ret = esp_tls_conn_read(tls, &rx_hdr, sizeof(rx_hdr));
    if (ret <= 0)
        return false;
    header_to_host(&rx_hdr);
    //[cite:3]

    AuthResPayload res_payload;
    esp_tls_conn_read(tls, &res_payload, sizeof(res_payload));

    if (rx_hdr.status == 0 && res_payload.status_code == 0)
    {
        //[cite:2, 3]
        ESP_LOGI(TAG, "AUTHENTICATION SUCCESSFUL! Session Token: %s", res_payload.session_token);
        return true;
    }
    else
    {
        ESP_LOGE(TAG, "AUTHENTICATION FAILED! Status Code: %d", res_payload.status_code);
        return false;
    }
}