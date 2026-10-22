/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/input/input.h>
#include <zephyr/authentication/fido2/fido2_up.h>
#include <zephyr/sys/atomic.h>

static K_SEM_DEFINE(pressed, 0, 1);
static atomic_t cancelled;
static atomic_t awaiting_press;

static void button_cb(struct input_event *evt, void *data)
{
    ARG_UNUSED(data);
    /* Only a new physical press during the request can approve it. */
    if (evt->type == INPUT_EV_KEY && evt->code == INPUT_KEY_0 && evt->value == 1 &&
        atomic_get(&awaiting_press)) {
        k_sem_give(&pressed);
    }
}
INPUT_CALLBACK_DEFINE(DEVICE_DT_GET(DT_CHOSEN(zephyr_fido2_up_input)), button_cb, NULL);

void fido2_up_reset(void)
{
    atomic_clear(&awaiting_press);
    atomic_clear(&cancelled);
    k_sem_reset(&pressed);
}

int fido2_up_wait(void)
{
    atomic_set(&awaiting_press, 1);
    int err = k_sem_take(&pressed, K_MSEC(CONFIG_FIDO2_UP_TIMEOUT_MS));
    atomic_clear(&awaiting_press);
    if (atomic_get(&cancelled)) { return -ECANCELED; }
    return err ? -ETIMEDOUT : 0;
}

void fido2_up_cancel(void)
{
    atomic_set(&cancelled, 1);
    k_sem_give(&pressed);
}
