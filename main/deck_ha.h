#pragma once
/* Home Assistant keys (docs/design/esphome.md, stage C): the "ha" and "hs" fields of the layout's key entries.
 * "ha" holds the actions the panel itself asks Home Assistant to run on a press, hold or double press, and "hs"
 * makes a key follow an HA entity. The table is filled from the same layout JSON as the buttons, on the USB push
 * and on layout_load, so the saved offline layout keeps its HA keys after a reboot without the PC.
 *
 * Thread contract as deck_model: every accessor takes this table's own mutex and copies in or out. The followed
 * states are drawn by deck_model_get_button (deck_ha_overlay), so a state changes a key's color, label or second
 * line in place (live_version) and never rebuilds it under a finger. Pure C with cJSON, compiled into tests/native. */
#include <stdbool.h>
#include <stdint.h>

#include "deck_model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define DECK_HA_STEPS_MAX 24        /* per page (layout budget) */
#define DECK_HA_TRIGGER_STEPS 2     /* per trigger of a key */
#define DECK_HA_FOLLOWS_MAX DECK_MAX_BUTTONS
#define DECK_HA_ACTION_MAX 64       /* "domain.service" */
#define DECK_HA_ENTITY_MAX 128      /* one id, or up to 4 comma-separated ids */
#define DECK_HA_ENTITIES 4
#define DECK_HA_DATA_MAX 4          /* data pairs per step */
#define DECK_HA_KEY_MAX 32
#define DECK_HA_VALUE_MAX 64        /* characters (UTF-8 code points) */
#define DECK_HA_ATTRIBUTE_MAX 32
#define DECK_HA_ON_MAX 4
#define DECK_HA_ON_TEXT_MAX 16      /* characters */
#define DECK_HA_UNIT_MAX 6          /* characters */
#define DECK_HA_STATE_MAX 63        /* bytes kept of a state; a longer one is cut at a UTF-8 boundary */
#define DECK_HA_OFF_COLOR 0x5A6270  /* the accent of a followed key whose state is not in "on" */
#define DECK_HA_STALE_BG 0x12191D   /* ui_palette Card: a state older than an HA disconnect fades toward it */

typedef struct {
    int button_id;
    char trigger; /* 'p' press, 'h' hold, 'd' double */
    char action[DECK_HA_ACTION_MAX + 1];
    char entity_id[DECK_HA_ENTITY_MAX + 1]; /* "" when none */
    uint8_t data_count;
    char keys[DECK_HA_DATA_MAX][DECK_HA_KEY_MAX + 1];
    char values[DECK_HA_DATA_MAX][DECK_HA_VALUE_MAX * 4 + 1];
} deck_ha_step_t;

typedef struct {
    int button_id;
    char entity_id[DECK_HA_ENTITY_MAX + 1];
    char attribute[DECK_HA_ATTRIBUTE_MAX + 1]; /* "" follows the state itself */
    char mode;                                 /* 'a' accent, 'v' value, 'b' both */
    uint8_t on_count;
    char on[DECK_HA_ON_MAX][DECK_HA_ON_TEXT_MAX * 4 + 1];
    char unit[DECK_HA_UNIT_MAX * 4 + 1];
} deck_ha_follow_t;

void deck_ha_init(void); /* from deck_model_init */

/* Checks the "ha"/"hs" fields of {"buttons":[...]} and, only when every one is valid, replaces the table. False
 * leaves the table as it was (the caller then answers INVALID and keeps the old buttons too). States of
 * entity/attribute pairs that are still followed are kept, so the host's frequent re-pushes lose nothing. */
bool deck_model_ha_from_json(const char *layout_json);
int deck_model_ha_steps(int button_id, char trigger, deck_ha_step_t *out, int max);
bool deck_model_ha_has_steps(int button_id, char trigger);
int deck_model_ha_follows(deck_ha_follow_t *out, int max);
/* Bumped only when the set of followed entity/attribute pairs changed: the API then subscribes again. */
uint32_t deck_model_ha_version(void);

/* A HomeAssistantStateResponse: updates every key following this pair. True when one did. */
bool deck_model_set_ha_state(const char *entity_id, const char *attribute, const char *state);
/* Home Assistant went away: the states stay but are drawn faded until a new one arrives. */
void deck_model_ha_mark_stale(void);

/* deck_model_get_button calls this with the model lock held: applies a known followed state to the copy. */
void deck_ha_overlay(deck_button_t *button);

/* Shared with the host's rules: ^[a-z_][a-z0-9_]*\.[a-z0-9_]+$ */
bool deck_ha_id_valid(const char *text, size_t len);

#ifdef __cplusplus
}
#endif
