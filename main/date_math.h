#pragma once

/*
 * Pure, platform-independent date math.
 *
 * date_math.c is the single home for the calendar arithmetic shared by the
 * firmware, the simulator and the host tests. It implements the pure part of
 * the time_service date API (declarations live in time_service.h):
 *   time_service_month_days, time_service_first_weekday,
 *   time_service_weekday_for_iso, time_service_week_number_for_iso,
 *   time_service_days_until_iso, time_service_add_days_iso and
 *   time_service_days_between_keys.
 *
 * "Today" hook: date math must not read any platform clock itself, so each
 * platform supplies today's date by overriding the weak date_math_today_key()
 * below (defined strongly in time_service.c on device and in sim_services.c
 * for the simulator and host tests). It returns today as a YYYYMMDD key
 * (e.g. 20260102), or 0 when the platform clock is unavailable.
 */
int date_math_today_key(void);
