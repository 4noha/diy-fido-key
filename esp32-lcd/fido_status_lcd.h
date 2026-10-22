#ifndef FIDO_STATUS_LCD_H
#define FIDO_STATUS_LCD_H

/* Starts the ST7735 status display task when the firmware is built with
 * FIDO_STATUS_LCD (ESP32-S3 target only). Safe to call once from app_main. */
void fido_status_lcd_init(void);

#endif
