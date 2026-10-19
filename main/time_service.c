#include "time_service.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_sntp.h"

#include "date_math.h"

static const char *TAG = "fq_time";
static char s_date_text[24] = "";
static char s_time_text[12] = "--:--";
static char s_iso_date[12] = "";

static bool s_manual_time = false;
/* Set from the SNTP callback once the network has corrected the clock; a
 * manual timestamp must not be presented as a reliable synchronized time. */
static volatile bool s_time_synced = false;

/* SNTP sets the system time itself before invoking this callback; here we
 * only record that the clock is now network-synchronized. */
static void sntp_time_synced_cb(struct timeval *tv)
{
    (void)tv;
    s_time_synced = true;
    ESP_LOGI(TAG, "Clock synchronized by SNTP");
}

static bool manual_time_is_valid(int year, int month, int day, int hour, int minute)
{
    return year >= 2024 &&
           month >= 1 && month <= 12 &&
           day >= 1 && day <= time_service_month_days(year, month) &&
           hour >= 0 && hour <= 23 &&
           minute >= 0 && minute <= 59;
}

esp_err_t time_service_init(void)
{
    setenv("TZ", "CET-1CEST,M3.5.0/2,M10.5.0/3", 1);
    tzset();

    esp_err_t err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "esp_netif_init failed: %s", esp_err_to_name(err));
        return err;
    }

    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "esp_event_loop_create_default failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "Time service ready with Oslo timezone");
    return ESP_OK;
}

void time_service_start_sntp(void)
{
    if (esp_sntp_enabled()) {
        return;
    }
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "pool.ntp.org");
    /* Must be registered before esp_sntp_init() to be delivered. */
    esp_sntp_set_time_sync_notification_cb(sntp_time_synced_cb);
    esp_sntp_init();
    ESP_LOGI(TAG, "SNTP started; waits for network to become available");
}

static bool local_time(struct tm *out_time)
{
    if (s_manual_time) {
        time_t now = 0;
        time(&now);
        return localtime_r(&now, out_time) != NULL;
    }
    time_t now = 0;
    time(&now);
    if (now < 1700000000) {
        return false;
    }
    return localtime_r(&now, out_time) != NULL;
}

void time_service_set_manual(int year, int month, int day, int hour, int minute)
{
    if (!manual_time_is_valid(year, month, day, hour, minute)) {
        ESP_LOGW(TAG, "Rejected invalid manual time: %04d-%02d-%02d %02d:%02d",
                 year, month, day, hour, minute);
        return;
    }
    struct tm tm_set = {0};
    tm_set.tm_year = year - 1900;
    tm_set.tm_mon = month - 1;
    tm_set.tm_mday = day;
    tm_set.tm_hour = hour;
    tm_set.tm_min = minute;
    tm_set.tm_sec = 0;
    tm_set.tm_isdst = -1;
    time_t t = mktime(&tm_set);
    struct timeval tv = { .tv_sec = t, .tv_usec = 0 };
    settimeofday(&tv, NULL);
    s_manual_time = true;
    /* A parent-set clock is no longer network-authoritative: quality drops
     * from SYNCED to MANUAL until SNTP corrects it again. */
    s_time_synced = false;
    s_date_text[0] = '\0';
    ESP_LOGI(TAG, "Manual time set: %04d-%02d-%02d %02d:%02d", year, month, day, hour, minute);
}

bool time_service_has_valid_time(void)
{
    struct tm tm_now = {0};
    return local_time(&tm_now);
}

time_quality_t time_service_time_quality(void)
{
    if (s_time_synced) {
        return TIME_SYNCED;
    }
    if (s_manual_time) {
        time_t now = 0;
        time(&now);
        return now >= 1700000000 ? TIME_MANUAL : TIME_UNKNOWN;
    }
    return TIME_UNKNOWN;
}

int time_service_today_key(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return (tm_now.tm_year + 1900) * 10000 + (tm_now.tm_mon + 1) * 100 + tm_now.tm_mday;
}

const char *time_service_date_text(void)
{
    static const char *weekdays[] = {"Søn", "Man", "Tir", "Ons", "Tor", "Fre", "Lør"};
    static const char *months[] = {
        "jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"
    };
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return "Klokke ikke stilt";
    }
    snprintf(s_date_text, sizeof(s_date_text), "%s %d. %s %d", weekdays[tm_now.tm_wday],
             tm_now.tm_mday, months[tm_now.tm_mon], tm_now.tm_year + 1900);
    return s_date_text;
}

const char *time_service_time_text(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return "--:--";
    }
    snprintf(s_time_text, sizeof(s_time_text), "%02d:%02d", tm_now.tm_hour, tm_now.tm_min);
    return s_time_text;
}

const char *time_service_iso_date(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return "";
    }
    int year = tm_now.tm_year + 1900;
    int month = tm_now.tm_mon + 1;
    int day = tm_now.tm_mday;
    if (year < 2000 || year > 2099) year = 2026;
    if (month < 1 || month > 12) month = 1;
    if (day < 1 || day > 31) day = 1;
    snprintf(s_iso_date, sizeof(s_iso_date), "%04d-%02d-%02d", year, month, day);
    return s_iso_date;
}

int time_service_week_number(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    char buf[8] = {0};
    strftime(buf, sizeof(buf), "%V", &tm_now);
    int w = atoi(buf);
    return w > 0 ? w : 1;
}

int time_service_week_key(void)
{
    const char *iso = time_service_iso_date();
    if (!iso || !iso[0]) {
        return 0;
    }
    /* ISO week-year = the civil year of this week's Thursday. Derived with
     * the shared date-math machinery so the key always agrees with
     * time_service_week_number_for_iso(), including year-boundary weeks. */
    int weekday = time_service_weekday_for_iso(iso);
    char thursday[12] = {0};
    if (!time_service_add_days_iso(iso, 3 - weekday, thursday, sizeof(thursday))) {
        return 0;
    }
    int iso_year = 0;
    if (sscanf(thursday, "%4d", &iso_year) != 1 || iso_year < 2000) {
        return 0;
    }
    int week = time_service_week_number_for_iso(iso);
    if (week <= 0) {
        return 0;
    }
    return iso_year * 100 + week;
}

int time_service_hour(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_hour;
}

int time_service_minute(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_min;
}

int time_service_weekday(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_wday == 0 ? 6 : tm_now.tm_wday - 1;
}

int time_service_year(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_year + 1900;
}

int time_service_month(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_mon + 1;
}

int time_service_day(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return tm_now.tm_mday;
}

/* Device clock override of the shared date-math "today" hook. */
int date_math_today_key(void)
{
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return 0;
    }
    return (tm_now.tm_year + 1900) * 10000 + (tm_now.tm_mon + 1) * 100 + tm_now.tm_mday;
}
