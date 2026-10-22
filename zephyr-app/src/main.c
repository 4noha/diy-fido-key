/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/settings/settings.h>
#include <zephyr/authentication/fido2/fido2.h>
#include <zephyr/authentication/fido2/fido2_transport.h>
#include <zephyr/sys/atomic.h>
#include <stdio.h>
#include <esp_bt.h>
#include <zephyr/input/input.h>
#include "oled.h"
#include "key_import.h"

LOG_MODULE_REGISTER(diy_fido, LOG_LEVEL_INF);
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static K_MUTEX_DEFINE(pairing_lock);
static struct bt_conn *pairing_conn;
static atomic_t state;
static atomic_t passkey = ATOMIC_INIT(-1);
static atomic_t connected;
static atomic_t comparison_pressed;

static void comparison_button(struct input_event *evt, void *data)
{
    ARG_UNUSED(data);
    if (evt->type == INPUT_EV_KEY && evt->code == INPUT_KEY_0 &&
        evt->value == 1 && atomic_get(&passkey) >= 0) {
        atomic_set(&comparison_pressed, 1);
    }
}
INPUT_CALLBACK_DEFINE(DEVICE_DT_GET(DT_CHOSEN(zephyr_fido2_up_input)),
                      comparison_button, NULL);
static void clear_pairing(void);

static const struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
    BT_DATA_BYTES(BT_DATA_UUID16_ALL, BT_UUID_16_ENCODE(FIDO2_BLE_SERVICE_UUID_VAL)),
};
static const uint8_t service_data[] = {
    BT_UUID_16_ENCODE(FIDO2_BLE_SERVICE_UUID_VAL), FIDO2_BLE_SERVICE_DATA_PAIRING_MODE,
};
static const struct bt_data sd[] = {
    BT_DATA(BT_DATA_SVC_DATA16, service_data, sizeof(service_data)),
    BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static void advertise(void)
{
    int err = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
    LOG_INF("BLE advertising result=%d", err);
}
static void on_connected(struct bt_conn *conn, uint8_t err)
{
    ARG_UNUSED(conn);
    atomic_set(&connected, err == 0);
    LOG_INF("BLE connected result=%u", err);
    if (err == 0) {
        int security_err = bt_conn_set_security(conn, BT_SECURITY_L3);
        LOG_INF("BLE security request=%d", security_err);
    }
}
static void on_disconnected(struct bt_conn *conn, uint8_t reason)
{
    ARG_UNUSED(conn);
    atomic_clear(&connected);
    clear_pairing();
    LOG_INF("BLE disconnected reason=%u", reason);
}
static void on_recycled(void) { advertise(); }
static void on_security(struct bt_conn *conn, bt_security_t level, enum bt_security_err err)
{
    ARG_UNUSED(conn);
    LOG_INF("BLE security level=%u result=%u", level, err);
}
BT_CONN_CB_DEFINE(connection_callbacks) = {
    .connected = on_connected, .disconnected = on_disconnected, .recycled = on_recycled,
    .security_changed = on_security,
};

static void display_passkey(struct bt_conn *conn, unsigned int key)
{
    ARG_UNUSED(conn);
    atomic_set(&passkey, key);
    LOG_INF("BLE pairing: passkey shown on OLED");
}
static void confirm_passkey(struct bt_conn *conn, unsigned int key)
{
    k_mutex_lock(&pairing_lock, K_FOREVER);
    if (pairing_conn) { bt_conn_unref(pairing_conn); }
    pairing_conn = bt_conn_ref(conn);
    atomic_clear(&comparison_pressed);
    atomic_set(&passkey, key);
    k_mutex_unlock(&pairing_lock);
    LOG_INF("BLE numeric comparison: compare OLED PIN and press BOOT");
}
static void clear_pairing(void)
{
    k_mutex_lock(&pairing_lock, K_FOREVER);
    if (pairing_conn) { bt_conn_unref(pairing_conn); pairing_conn = NULL; }
    atomic_set(&passkey, -1);
    atomic_clear(&comparison_pressed);
    k_mutex_unlock(&pairing_lock);
}
static void pairing_cancel(struct bt_conn *conn)
{
    ARG_UNUSED(conn);
    clear_pairing();
}
static void pairing_complete(struct bt_conn *conn, bool bonded)
{
    ARG_UNUSED(conn);
    clear_pairing();
    LOG_INF("BLE pairing completed bonded=%d", bonded);
}
static void pairing_failed(struct bt_conn *conn, enum bt_security_err reason)
{
    ARG_UNUSED(conn);
    clear_pairing();
    LOG_WRN("BLE pairing failed reason=%u", reason);
}
static const struct bt_conn_auth_cb auth_callbacks = {
    .passkey_display = display_passkey, .passkey_confirm = confirm_passkey,
    .cancel = pairing_cancel,
};
static struct bt_conn_auth_info_cb auth_info_callbacks = {
    .pairing_complete = pairing_complete, .pairing_failed = pairing_failed,
};

static void state_changed(enum fido2_runtime_state current, void *data)
{
    ARG_UNUSED(data);
    atomic_set(&state, current);
    LOG_INF("FIDO state=%d", current);
}

int main(void)
{
    int err;
    oled_init();
    gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
    err = fido2_init();
    if (err) { LOG_ERR("FIDO init=%d", err); oled_status("Init failed", "See USB log"); return err; }
    key_import_boot_mode();
    fido2_set_state_callback(state_changed, NULL);
    err = fido2_start();
    if (err) { return err; }
    bt_conn_auth_cb_register(&auth_callbacks);
    bt_conn_auth_info_cb_register(&auth_info_callbacks);
    err = bt_enable(NULL);
    if (err) { LOG_ERR("BLE init=%d", err); return err; }
    err = settings_load();
    if (err) { LOG_ERR("Settings load=%d", err); return err; }
    err = esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_DEFAULT, ESP_PWR_LVL_P9);
    LOG_INF("BLE default TX power +9 dBm result=%d", err);
    err = esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, ESP_PWR_LVL_P9);
    LOG_INF("BLE advertising TX power +9 dBm result=%d", err);
    advertise();
    LOG_INF("DIY FIDO2 BLE ready: BOOT confirms presence; OLED shows pairing PIN");
    unsigned int tick = 0;
    int last_key = -2, last_state = -1, last_connected = -1;
    while (1) {
        char detail[16];
        int key = atomic_get(&passkey);
        int current = atomic_get(&state);
        int link = atomic_get(&connected);
        if (atomic_cas(&comparison_pressed, 1, 0)) {
            k_mutex_lock(&pairing_lock, K_FOREVER);
            struct bt_conn *confirm = pairing_conn;
            pairing_conn = NULL;
            k_mutex_unlock(&pairing_lock);
            if (confirm) {
                int result = bt_conn_auth_passkey_confirm(confirm);
                LOG_INF("BOOT confirmed BLE comparison result=%d", result);
                bt_conn_unref(confirm);
            }
        }
        if (key != last_key || current != last_state || link != last_connected) {
            if (key >= 0) {
                snprintf(detail, sizeof(detail), "%06d", key);
                oled_status("PIN + BOOT", detail);
            } else if (current == FIDO2_RUNTIME_STATE_WAITING_USER_PRESENCE) {
                oled_status("Press BOOT", "Confirm now");
            } else if (current == FIDO2_RUNTIME_STATE_PROCESSING) {
                oled_status("Processing", "Please wait");
            } else {
                oled_status("Ready", link ? "Connected" : "Pair via BLE");
            }
            last_key = key;
            last_state = current;
            last_connected = link;
        }
        gpio_pin_set_dt(&led, current == FIDO2_RUNTIME_STATE_PROCESSING ||
            (current == FIDO2_RUNTIME_STATE_WAITING_USER_PRESENCE && tick % 2));
        tick++;
        k_msleep(200);
    }
}
