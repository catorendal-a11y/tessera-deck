#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* The panel has no network clock: the USB host sends the PC's local time (AD_TIME). */
esp_err_t time_service_init(void);
/* Returns false when the value is not a valid date and time; the clock is then left as it was. */
bool time_service_set_from_host(int year, int month, int day, int hour, int minute, int second);
const char *time_service_date_text(void);  /* "Tue 20 Oct 2026", or "Clock not set" */
const char *time_service_time_text(void);  /* "14:32", or "--:--" */

#ifdef __cplusplus
}
#endif
