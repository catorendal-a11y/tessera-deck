#include "time_service.h"

#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>
#include <time.h>

#include "esp_log.h"

static const char *TAG = "fq_time";
static char s_date_text[24] = "";
static char s_time_text[12] = "--:--";

static int month_days(int year, int month)
{
    static const int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    const bool leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    return month == 2 && leap ? 29 : days[month - 1];
}

esp_err_t time_service_init(void)
{
    /* The panel has no network: its only clock source is the PC, which sends its own local time (AD_TIME) every
     * few minutes. Keeping the panel in UTC shows exactly that time in every country; a fixed zone would apply
     * its own daylight-saving switch on top of the PC's. */
    setenv("TZ", "UTC0", 1);
    tzset();
    ESP_LOGI(TAG, "Time service ready; the clock follows the PC");
    return ESP_OK;
}

/* False until the PC has set a plausible time (the chip starts in 1970). */
static bool local_time(struct tm *out_time)
{
    time_t now = 0;
    time(&now);
    return now >= 1700000000 && localtime_r(&now, out_time) != NULL;
}

bool time_service_set_from_host(int year, int month, int day, int hour, int minute, int second)
{
    if (year < 2024 || month < 1 || month > 12 || day < 1 || day > month_days(year, month) ||
        hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) {
        ESP_LOGW(TAG, "Rejected an invalid time from the PC: %04d-%02d-%02d %02d:%02d", year, month, day, hour, minute);
        return false;
    }
    struct tm tm_set = {0};
    tm_set.tm_year = year - 1900;
    tm_set.tm_mon = month - 1;
    tm_set.tm_mday = day;
    tm_set.tm_hour = hour;
    tm_set.tm_min = minute;
    tm_set.tm_sec = second;
    tm_set.tm_isdst = -1;
    struct timeval tv = { .tv_sec = mktime(&tm_set), .tv_usec = 0 };
    settimeofday(&tv, NULL);
    ESP_LOGI(TAG, "Time set from the PC: %04d-%02d-%02d %02d:%02d", year, month, day, hour, minute);
    return true;
}

const char *time_service_date_text(void)
{
    static const char *weekdays[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    static const char *months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    };
    struct tm tm_now = {0};
    if (!local_time(&tm_now)) {
        return "Clock not set";
    }
    snprintf(s_date_text, sizeof(s_date_text), "%s %d %s %d", weekdays[tm_now.tm_wday],
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
