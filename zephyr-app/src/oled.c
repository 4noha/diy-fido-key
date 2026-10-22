/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <u8g2.h>
#include "oled.h"

static const struct device *bus = DEVICE_DT_GET(DT_NODELABEL(i2c0));
static u8g2_t oled;
static uint8_t tx[32];
static size_t tx_len;
static bool ready;

static uint8_t byte_cb(u8x8_t *display, uint8_t msg, uint8_t len, void *data)
{
    switch (msg) {
    case U8X8_MSG_BYTE_INIT: return device_is_ready(bus);
    case U8X8_MSG_BYTE_START_TRANSFER: tx_len = 0; return 1;
    case U8X8_MSG_BYTE_SEND:
        if (tx_len + len > sizeof(tx)) { return 0; }
        memcpy(tx + tx_len, data, len);
        tx_len += len;
        return 1;
    case U8X8_MSG_BYTE_END_TRANSFER:
        return i2c_write(bus, tx, tx_len, u8x8_GetI2CAddress(display) >> 1) == 0;
    case U8X8_MSG_BYTE_SET_DC: return 1;
    default: return 0;
    }
}

static uint8_t delay_cb(u8x8_t *display, uint8_t msg, uint8_t arg, void *data)
{
    ARG_UNUSED(display); ARG_UNUSED(data);
    switch (msg) {
    case U8X8_MSG_GPIO_AND_DELAY_INIT: return 1;
    case U8X8_MSG_DELAY_MILLI: k_msleep(arg); return 1;
    case U8X8_MSG_DELAY_10MICRO: k_busy_wait(arg * 10); return 1;
    case U8X8_MSG_DELAY_NANO: k_busy_wait(1); return 1;
    default: return 1;
    }
}

int oled_init(void)
{
    if (!device_is_ready(bus)) { return -ENODEV; }
    u8g2_Setup_ssd1306_i2c_128x64_noname_f(&oled, U8G2_R0, byte_cb, delay_cb);
    u8g2_SetI2CAddress(&oled, 0x3c << 1);
    u8g2_InitDisplay(&oled);
    u8g2_SetPowerSave(&oled, 0);
    u8g2_SetContrast(&oled, 128);
    ready = true;
    oled_status("Starting", "Zephyr BLE");
    return 0;
}

void oled_status(const char *state, const char *detail)
{
    if (!ready) { return; }
    u8g2_ClearBuffer(&oled);
    u8g2_SetFont(&oled, u8g2_font_5x7_tr);
    u8g2_DrawFrame(&oled, 28, 24, 72, 40);
    u8g2_DrawStr(&oled, 31, 34, "FIDO2 BLE");
    u8g2_DrawStr(&oled, 31, 46, state);
    u8g2_DrawStr(&oled, 31, 58, detail);
    u8g2_SendBuffer(&oled);
}
