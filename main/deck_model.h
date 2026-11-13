#pragma once

/* Tessera shared model: the single source of truth for deck buttons,
 * navigation context and press events.
 *
 * Thread contract: every accessor takes the internal mutex and copies
 * data in/out, so the USB console task and the LVGL timer can both use
 * it without sharing pointers. UI refresh is driven
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
    bool has_double;                   /* the host has a double-press action: only drawn as a mark; the host tells taps apart */
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
    char gauge_badge[DECK_ICON_NAME_MAX + 1]; /* optional Lucide icon for what the gauge measures */
    /* Wide key (protocol 4): covers `span` slots to the right; shows a title, a second line and a progress bar or ring. */
    uint8_t span;                      /* 1..3; 0 from an older host counts as 1 */
    char sub[41];                      /* second line, for example the artist */
    bool has_progress;
    uint8_t progress;                  /* 0..100 */
    bool ring;                         /* draw the progress as a ring instead of a bar */
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

/* Host link: every line from the host stamps it; the foot of the rail shows
 * NO PC when no host has spoken within the timeout. */
void deck_model_note_host(void);
bool deck_model_host_linked(int64_t timeout_ms);

/* Cockpit screens (protocol 4): beside the keys the panel shows the AI agents, a sound mixer and the PC's
 * vital signs. The host sends each as one JSON line; the UI redraws when the version changes. */
#define DECK_AGENTS_MAX 3
#define DECK_FADERS_MAX 5
#define DECK_STATS_MAX 8
#define DECK_ID_MAX 39
typedef enum { DECK_AGENT_IDLE = 0, DECK_AGENT_WORKING = 1, DECK_AGENT_WAITING = 2 } deck_agent_state_t;
typedef struct {
    char id[DECK_ID_MAX + 1];
    char name[24];
    uint8_t state;   /* deck_agent_state_t */
    char text[160];  /* what it is doing or asking; a permission prompt is shown in full */
    char sub[32];    /* project */
} deck_agent_t;
typedef struct {
    char id[DECK_ID_MAX + 1]; /* the host's audio target: speaker, mic or app:NAME.exe */
    char name[16];
    uint8_t level;            /* 0..100 */
    bool muted;
    bool mic;
    uint32_t color;
} deck_fader_t;
typedef struct {
    char name[16];
    char value[8];
    char unit[6];
    uint8_t percent;
    uint32_t color;
    bool warn;
} deck_stat_t;
bool deck_model_agents_from_json(const char *json_text);  /* {"agents":[{id,name,state,text,sub}]} */
bool deck_model_faders_from_json(const char *json_text);  /* {"faders":[{id,name,level,muted,mic,color}]} */
bool deck_model_stats_from_json(const char *json_text);   /* {"stats":[{name,value,unit,p,color,warn}]} */
int deck_model_agents(deck_agent_t *out, int max_out);
int deck_model_faders(deck_fader_t *out, int max_out);
int deck_model_stats(deck_stat_t *out, int max_out);
uint32_t deck_model_agents_version(void);
uint32_t deck_model_faders_version(void);
uint32_t deck_model_stats_version(void);
/* The rail (protocol 4): which screens have a button, and the shortcuts to a page of a profile. */
#define DECK_RAIL_MAX 7
typedef struct {
    uint8_t kind;                      /* 0 keys, 1 agents, 2 mixer, 3 status, 4 page shortcut */
    char icon[DECK_ICON_NAME_MAX + 1]; /* shortcut icon, a Lucide name like lc:e0e8 */
    char profile[DECK_CONTEXT_TEXT_MAX + 1];
    char page[DECK_CONTEXT_TEXT_MAX + 1];
} deck_rail_item_t;
bool deck_model_rail_from_json(const char *json_text);  /* {"rail":[{"k":"keys"},{"k":"page","i":"lc:e0e8","p":"Chrome","g":"main"}]} */
int deck_model_rail(deck_rail_item_t *out, int max_out);
uint32_t deck_model_rail_version(void);
/* The host can bring one of the four screens to the front (a permission prompt opens the agents screen). */
void deck_model_request_view(int view);
int deck_model_take_view_request(void); /* -1 when nothing is pending */
/* A touch the host must hear about (an agent button, a fader): one ready JSON line, sent by the USB console. */
void deck_model_queue_line(const char *line);
bool deck_model_take_line(char *out, size_t size);

/* Parser for the layout the host pushes over the USB console.
 * Accepts {"buttons":[...]} text; returns false (count untouched) on any
 * invalid entry. */
bool deck_model_buttons_from_json(const char *json_text, deck_button_t *out,
                                  int max_out, int *count);

#ifdef __cplusplus
}
#endif
