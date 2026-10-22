/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/random/random.h>
#include <zephyr/psa/key_ids.h>
#include <zephyr/authentication/fido2/fido2_storage.h>
#include <zephyr/input/input.h>
#include <zephyr/sys/atomic.h>
#include <psa/crypto.h>
#include <mbedtls/platform_util.h>
#include <string.h>
#include "oled.h"
#include "key_import.h"

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct device *const serial = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
static uint8_t packet[359]; /* lengths(3), count(4), scalar(32), RP(127), user(64), ID(128) */
static struct fido2_credential imported;
static K_SEM_DEFINE(import_pressed, 0, 1);
static atomic_t awaiting_import;

static void import_button(struct input_event *evt, void *data)
{
    ARG_UNUSED(data);
    if (evt->type == INPUT_EV_KEY && evt->code == INPUT_KEY_0 &&
        evt->value == 1 && atomic_get(&awaiting_import)) {
        k_sem_give(&import_pressed);
    }
}
INPUT_CALLBACK_DEFINE(DEVICE_DT_GET(DT_CHOSEN(zephyr_fido2_up_input)), import_button, NULL);

static void send_text(const char *text)
{
    while (*text) { uart_poll_out(serial, *text++); }
}
static int read_exact(uint8_t *data, size_t len, int64_t deadline)
{
    for (size_t i = 0; i < len;) {
        if (k_uptime_get() > deadline) { return -ETIMEDOUT; }
        if (uart_poll_in(serial, &data[i]) == 0) { i++; }
        else { k_msleep(1); }
    }
    return 0;
}
static int import_packet(size_t length, uint8_t public_key[65])
{
    uint8_t rp_len = packet[0], user_len = packet[1], id_len = packet[2];
    if (length < 39 || !rp_len || rp_len >= sizeof(imported.rp_id) ||
        !user_len || user_len > sizeof(imported.user_id) ||
        !id_len || id_len > sizeof(imported.id) ||
        length != (size_t)39 + rp_len + user_len + id_len) { return -EINVAL; }
    /* Accept a lowercase ASCII RP identifier, never a URL or embedded NUL. */
    for (size_t i = 39; i < 39 + rp_len; i++) {
        uint8_t c = packet[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '.')) {
            return -EINVAL;
        }
    }
    memcpy(imported.id, packet + 39 + rp_len + user_len, id_len);
    imported.id_len = id_len;
    struct fido2_credential existing;
    int err = fido2_storage_load(imported.id, id_len, &existing);
    mbedtls_platform_zeroize(&existing, sizeof(existing));
    if (err == 0) { return -EEXIST; }
    if (err != -ENOENT) { return err; }
    memcpy(imported.rp_id, packet + 39, rp_len);
    memcpy(imported.user_id, packet + 39 + rp_len, user_len);
    imported.user_id_len = user_len;
    imported.sign_count = sys_get_be32(packet + 3);
    if (imported.sign_count == UINT32_MAX) { return -EINVAL; }
    imported.algorithm = FIDO2_COSE_ES256;
    imported.discoverable = true;
    strcpy(imported.user_name, "USB imported");
    strcpy(imported.user_display_name, "USB imported");
    size_t hash_len;
    if (psa_hash_compute(PSA_ALG_SHA_256, (uint8_t *)imported.rp_id, rp_len,
                         imported.rp_id_hash, 32, &hash_len) != PSA_SUCCESS) { return -EIO; }
    oled_status("Import? BOOT", imported.rp_id);
    send_text("\nDFI:CONFIRM\n");
    /* Require a released button followed by a fresh physical press. */
    int64_t release_deadline = k_uptime_get() + 30000;
    while (gpio_pin_get_dt(&button) == 1) {
        if (k_uptime_get() > release_deadline) { return -ETIMEDOUT; }
        k_msleep(10);
    }
    k_sem_reset(&import_pressed);
    atomic_set(&awaiting_import, 1);
    err = k_sem_take(&import_pressed, K_SECONDS(120));
    atomic_clear(&awaiting_import);
    if (err) { return -EACCES; }
    psa_status_t status = PSA_ERROR_ALREADY_EXISTS;
    for (int i = 0; i < 32 && status == PSA_ERROR_ALREADY_EXISTS; i++) {
        psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
        psa_key_id_t candidate = ZEPHYR_PSA_FIDO2_KEY_ID_RANGE_BEGIN + 1 +
            sys_rand32_get() % (ZEPHYR_PSA_FIDO2_KEY_ID_RANGE_SIZE - 1);
        psa_set_key_type(&attr, PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_SECP_R1));
        psa_set_key_bits(&attr, 256);
        psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_SIGN_HASH);
        psa_set_key_algorithm(&attr, PSA_ALG_ECDSA(PSA_ALG_SHA_256));
        psa_set_key_lifetime(&attr, PSA_KEY_LIFETIME_PERSISTENT);
        psa_set_key_id(&attr, candidate);
        status = psa_import_key(&attr, packet + 7, 32, &imported.key_id);
        psa_reset_key_attributes(&attr);
    }
    mbedtls_platform_zeroize(packet + 7, 32);
    if (status != PSA_SUCCESS) { return -EIO; }
    size_t public_len;
    status = psa_export_public_key(imported.key_id, public_key, 65, &public_len);
    if (status != PSA_SUCCESS || public_len != 65) { err = -EIO; }
    else { err = fido2_storage_store(&imported); }
    if (err) { psa_destroy_key(imported.key_id); }
    return err;
}
void key_import_boot_mode(void)
{
    oled_status("Starting", "USB window 5s");
    send_text("\nDFI:READY\n");
    uint8_t header[6], public_key[65] = {0};
    int err = read_exact(header, sizeof(header), k_uptime_get() + 5000);
    if (err == -ETIMEDOUT) { return; }
    if (!err && memcmp(header, "DFI1", 4)) { err = -EINVAL; }
    size_t length = err ? 0 : sys_get_be16(header + 4);
    if (!err && (length < 39 || length > sizeof(packet))) { err = -EINVAL; }
    if (!err) { err = read_exact(packet, length, k_uptime_get() + 10000); }
    if (!err) { err = import_packet(length, public_key); }
    mbedtls_platform_zeroize(packet, sizeof(packet));
    mbedtls_platform_zeroize(&imported, sizeof(imported));
    if (err) {
        char failure[32];
        snprintk(failure, sizeof(failure), "\nDFI:ERROR:%d\n", err);
        send_text(failure); oled_status("Import failed", "Restart normal");
    } else {
        static const char hex[] = "0123456789abcdef";
        send_text("\nDFI:OK:");
        for (size_t i = 0; i < sizeof(public_key); i++) {
            uart_poll_out(serial, hex[public_key[i] >> 4]);
            uart_poll_out(serial, hex[public_key[i] & 15]);
        }
        send_text("\n"); oled_status("Imported", "Restart normal");
    }
    k_msleep(500);
    sys_reboot(SYS_REBOOT_COLD);
    while (1) { k_msleep(1000); }
}
