#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* How trustworthy the clock is (implementation plan section 8): a boot-time
 * clock with no set point and an insane epoch is UNKNOWN, a clock set by the
 * parent in Settings is MANUAL, and a clock corrected by SNTP is SYNCED. */
typedef enum {
    TIME_UNKNOWN = 0,
    TIME_MANUAL,
    TIME_SYNCED,
} time_quality_t;

esp_err_t time_service_init(void);
void time_service_start_sntp(void);
void time_service_set_manual(int year, int month, int day, int hour, int minute);
/* Local time from the USB host, used while SNTP has not synchronized the clock
 * (no Wi-Fi). Returns false when SNTP time is kept or the value is invalid. */
bool time_service_set_from_host(int year, int month, int day, int hour, int minute, int second);
bool time_service_has_valid_time(void);
time_quality_t time_service_time_quality(void);
int time_service_today_key(void);
const char *time_service_date_text(void);
const char *time_service_time_text(void);
const char *time_service_iso_date(void);
int time_service_week_number(void);
/* Unambiguous ISO week key: ISO week-year * 100 + week (e.g. 202621 for week
 * 21 of ISO year 2026). Week 1 of early January and week 52/53 of late
 * December no longer collide across years. 0 when time is unknown. */
int time_service_week_key(void);
int time_service_hour(void);
int time_service_minute(void);
int time_service_weekday(void);
int time_service_year(void);
int time_service_month(void);
int time_service_day(void);
int time_service_month_days(int year, int month);
int time_service_first_weekday(int year, int month);
int time_service_weekday_for_iso(const char *iso_date);
int time_service_week_number_for_iso(const char *iso_date);
int time_service_days_until_iso(const char *iso_date);
bool time_service_add_days_iso(const char *iso_date, int days, char *out_date, size_t out_size);
/* Day difference between two YYYYMMDD keys (newer - older); 9999 on invalid input. */
int time_service_days_between_keys(int older_key, int newer_key);

#ifdef __cplusplus
}
#endif
