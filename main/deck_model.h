#pragma once

/* Tessera shared model: the single source of truth for deck buttons,
 * navigation context and press events.
 *
 * Thread contract: every accessor takes the internal mutex and copies
 * data in/out, so the HTTP server task, the LVGL timer and the USB
 * console can all use it without sharing pointers. UI refresh is driven
 * by the monotonically increasing version counters, never by callbacks
 * from other tasks. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DECK_MAX_BUTTONS 18
#define DECK_BUTTON_LABEL_MAX 24
#define DECK_ICON_NAME_MAX 15
#define DECK_EVENT_RING 32
#define DECK_CONTEXT_TEXT_MAX 31
#define DECK_GAUGE_TEXT_MAX 7
#define DECK_AMBIENT_MAX 80

#define DECK_STYLE_BG 1
#define DECK_STYLE_TEXT 2
#define DECK_STYLE_BORDER 4

typedef struct {
    int id;
    char label[DECK_BUTTON_LABEL_MAX + 1];
    char icon[DECK_ICON_NAME_MAX + 1]; /* logical name, mapped to LV_SYMBOL in ui */
    uint32_t color;                    /* 0xRRGGBB accent */
    uint8_t title_size;                /* 0 uses legacy 16px */
    uint8_t title_position;            /* 0 bottom, 1 top, 2 middle, 3 hidden */
    bool title_bold;
    bool has_hold;                     /* the host has a long-press action: report holds, not clicks, past the hold time */
    uint8_t style;                     /* DECK_STYLE_* bits: which of the colors below replace the defaults */
    uint32_t bg;                       /* key background */
    uint32_t text;                     /* label color */
    uint32_t border;                   /* key outline */
    /* Live gauge tile: a ring filled to gauge_percent with gauge_text in the middle.
     * label, color, gauge_percent and gauge_text change in place without a rebuild,
     * so dynamic labels and status colors never tear down a key under a finger. */
    bool has_gauge;
    uint8_t gauge_percent;             /* 0..100 */
    char gauge_text[DECK_GAUGE_TEXT_MAX + 1];
} deck_button_t;

typedef struct {
    int id;      /* monotonic event id, survives ring wrap */
    int button_id;
    bool hold;   /* long press instead of a click */
    char label[DECK_BUTTON_LABEL_MAX + 1];
    int64_t timestamp_ms;
} deck_event_t;

typedef struct {
    char profile[DECK_CONTEXT_TEXT_MAX + 1];
    char page[DECK_CONTEXT_TEXT_MAX + 1];
    bool can_go_back;
} deck_context_t;

void deck_model_init(void);
void deck_model_defaults(void);

/* Buttons */
int deck_model_button_count(void);
bool deck_model_get_button(int index, deck_button_t *out);
bool deck_model_replace_buttons(const deck_button_t *buttons, int count);
uint32_t deck_model_buttons_version(void);
/* Bumped when only live gauge values changed; the UI updates them in place. */
uint32_t deck_model_live_version(void);
void deck_model_set_context(const char *profile, const char *page, bool can_go_back);
deck_context_t deck_model_context(void);
uint32_t deck_model_context_version(void);

/* Press events */
uint32_t deck_model_record_press(int button_id); /* returns new event id, 0 if unknown button */
uint32_t deck_model_record_hold(int button_id);  /* same, flagged as a long press */
int deck_model_events_since(int since_id, deck_event_t *out, int max_out);
int deck_model_last_event_id(void);
uint32_t deck_model_events_total(void);

/* Key feedback (host confirms success/failure): consumed by the UI timer. */
typedef enum {
    DECK_FEEDBACK_OK = 0,
    DECK_FEEDBACK_ALERT,
} deck_feedback_t;
void deck_model_request_feedback(int button_id, deck_feedback_t kind);
/* Pops the oldest pending confirmation: returns its sequence number and fills
 * the details, or 0 when none is queued. Confirmations that arrive between two
 * UI ticks are kept in order instead of overwriting each other. */
uint32_t deck_model_take_feedback(int *button_id, deck_feedback_t *kind);

/* Display state. The host dims the backlight; a touch on a dimmed panel asks
 * for a local wake instead of pressing a key. The USB console applies the
 * wake and tells the host, so the wake works even on empty slots. */
void deck_model_set_dimmed(bool dimmed);
bool deck_model_dimmed(void);
void deck_model_request_wake(void); /* clears dimmed and bumps the sequence */
uint32_t deck_model_wake_sequence(void);

/* Screens: the host asks for the ambient clock when the panel is idle; the UI applies the request on its own
 * timer. A touch on the ambient screen returns to the deck and is reported once to the host. */
typedef enum { DECK_SCREEN_DECK = 0, DECK_SCREEN_AMBIENT = 1 } deck_screen_t;
void deck_model_request_screen(deck_screen_t screen);
int deck_model_take_screen_request(void); /* -1 when nothing is pending */
void deck_model_set_screen(deck_screen_t screen);
deck_screen_t deck_model_screen(void);
void deck_model_note_touch_return(void);
bool deck_model_take_touch_return(void);
void deck_model_set_ambient(const char *line); /* weather or status line under the clock */
void deck_model_ambient(char *out, size_t size);
uint32_t deck_model_ambient_version(void);

/* Host link: every line from the host stamps it; the header shows whether a
 * host has spoken within the timeout. */
void deck_model_note_host(void);
bool deck_model_host_linked(int64_t timeout_ms);

/* Shared parser for both the HTTP API and the USB console config push.
 * Accepts {"buttons":[...]} text; returns false (count untouched) on any
 * invalid entry. */
bool deck_model_buttons_from_json(const char *json_text, deck_button_t *out,
                                  int max_out, int *count);

#ifdef __cplusplus
}
#endif
