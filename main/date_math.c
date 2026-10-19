#include "date_math.h"

#include <stdio.h>
#include <stdbool.h>
#include <stddef.h>

/*
 * Shared, pure date math. No platform headers here: only standard C, so the
 * same object serves the firmware, the simulator and the host tests.
 *
 * "Today" comes from date_math_today_key(): a weak default returning 0 that
 * each platform overrides (time_service.c on device, sim_services.c elsewhere).
 */

__attribute__((weak)) int date_math_today_key(void)
{
    return 0;
}

int time_service_month_days(int year, int month)
{
    static const int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    if (month < 1 || month > 12) {
        return 30;
    }
    int d = days[month - 1];
    if (month == 2 && ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) {
        d = 29;
    }
    return d;
}

int time_service_first_weekday(int year, int month)
{
    static const int month_offsets[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
    if (month < 1 || month > 12) {
        return 0;
    }
    year -= month < 3;
    int wday = (year + year / 4 - year / 100 + year / 400 + month_offsets[month - 1] + 1) % 7;
    return wday == 0 ? 6 : wday - 1;
}

static bool parse_iso_date(const char *iso_date, int *year, int *month, int *day)
{
    if (!iso_date || !year || !month || !day) {
        return false;
    }
    if (sscanf(iso_date, "%4d-%2d-%2d", year, month, day) != 3 ||
        *year < 2020 || *month < 1 || *month > 12 || *day < 1 ||
        *day > time_service_month_days(*year, *month)) {
        return false;
    }
    return true;
}

static int civil_day_number(int year, unsigned month, unsigned day)
{
    year -= month <= 2;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yoe = (unsigned)(year - era * 400);
    const unsigned shifted_month = (unsigned)((int)month + (month > 2 ? -3 : 9));
    const unsigned doy = (153 * shifted_month + 2) / 5 + day - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + (int)doe;
}

static void civil_from_day_number(int day_number, int *year, int *month, int *day)
{
    const int era = (day_number >= 0 ? day_number : day_number - 146096) / 146097;
    const unsigned doe = (unsigned)(day_number - era * 146097);
    const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const int y = (int)yoe + era * 400;
    const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const unsigned mp = (5 * doy + 2) / 153;
    const unsigned d = doy - (153 * mp + 2) / 5 + 1;
    const unsigned m = mp + (mp < 10 ? 3 : -9);
    if (year) *year = y + (m <= 2);
    if (month) *month = (int)m;
    if (day) *day = (int)d;
}

int time_service_weekday_for_iso(const char *iso_date)
{
    int year = 0;
    int month = 0;
    int day = 0;
    if (!parse_iso_date(iso_date, &year, &month, &day)) {
        return 0;
    }
    int w = (civil_day_number(year, (unsigned)month, (unsigned)day) + 2) % 7;
    return w < 0 ? w + 7 : w;
}

int time_service_week_number_for_iso(const char *iso_date)
{
    int year = 0;
    int month = 0;
    int day = 0;
    if (!parse_iso_date(iso_date, &year, &month, &day)) {
        return 0;
    }
    int ordinal = civil_day_number(year, (unsigned)month, (unsigned)day);
    int weekday = (ordinal + 2) % 7;
    if (weekday < 0) weekday += 7;
    int thursday = ordinal + (3 - weekday);
    int iso_year = 0;
    civil_from_day_number(thursday, &iso_year, NULL, NULL);
    int jan4 = civil_day_number(iso_year, 1, 4);
    int jan4_weekday = (jan4 + 2) % 7;
    if (jan4_weekday < 0) jan4_weekday += 7;
    int week1_monday = jan4 - jan4_weekday;
    int week = (ordinal - week1_monday) / 7 + 1;
    return week > 0 ? week : 1;
}

int time_service_days_until_iso(const char *iso_date)
{
    if (!iso_date || !iso_date[0]) {
        return 0;
    }

    int target_year = 0;
    int target_month = 0;
    int target_day = 0;
    if (!parse_iso_date(iso_date, &target_year, &target_month, &target_day)) {
        return 9999;
    }

    int today = date_math_today_key();
    if (today <= 0) {
        return 9999;
    }

    int today_ordinal = civil_day_number(today / 10000, (unsigned)((today / 100) % 100), (unsigned)(today % 100));
    int target_ordinal = civil_day_number(target_year, (unsigned)target_month, (unsigned)target_day);
    return target_ordinal - today_ordinal;
}

bool time_service_add_days_iso(const char *iso_date, int days, char *out_date, size_t out_size)
{
    if (!out_date || out_size < 11) {
        return false;
    }

    char today_text[12] = {0};
    const char *source = (iso_date && iso_date[0]) ? iso_date : NULL;
    if (!source) {
        int today = date_math_today_key();
        if (today <= 0) {
            return false;
        }
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wformat-truncation"
        snprintf(today_text, sizeof(today_text), "%04d-%02d-%02d",
                 today / 10000, (today / 100) % 100, today % 100);
#pragma GCC diagnostic pop
        source = today_text;
    }

    int year = 0;
    int month = 0;
    int day = 0;
    if (!parse_iso_date(source, &year, &month, &day)) {
        return false;
    }

    int target_year = 0;
    int target_month = 0;
    int target_day = 0;
    civil_from_day_number(civil_day_number(year, (unsigned)month, (unsigned)day) + days,
                          &target_year, &target_month, &target_day);
    snprintf(out_date, out_size, "%04d-%02d-%02d",
             target_year, target_month, target_day);
    return true;
}

static bool day_key_to_ordinal(int key, int *ordinal)
{
    if (key < 20200101 || !ordinal) {
        return false;
    }
    int year = key / 10000;
    int month = (key / 100) % 100;
    int day = key % 100;
    if (month < 1 || month > 12 || day < 1 || day > time_service_month_days(year, month)) {
        return false;
    }
    *ordinal = civil_day_number(year, (unsigned)month, (unsigned)day);
    return true;
}

int time_service_days_between_keys(int older_key, int newer_key)
{
    int older_day = 0;
    int newer_day = 0;
    if (!day_key_to_ordinal(older_key, &older_day) || !day_key_to_ordinal(newer_key, &newer_day)) {
        return 9999;
    }
    return newer_day - older_day;
}
