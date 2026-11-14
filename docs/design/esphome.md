# ESPHome inside Tessera

Status: design, nothing built yet. Applies to firmware `main/` (ESP-IDF 6.1, LVGL 9.6), the host `host/` and the editor `host/editor/`.

The goal: the panel joins Wi-Fi and shows up in Home Assistant (HA) as an ESPHome device over the native API, with mDNS discovery and Noise encryption. USB to Windows keeps working exactly as it does today. Keys can call HA actions and show entity state, even when the PC is off.

Three stages. Each one ships on its own and leaves the panel fully usable over USB:

| Stage | Ships | Needs |
|---|---|---|
| A | Wi-Fi over the ESP32-C6 (ESP-Hosted, SDIO). Credentials sent over USB. Status on the panel and in the editor. | nothing |
| B | ESPHome native API server (Noise, mDNS), entities for keys, profile/page, backlight, Wi-Fi signal, clock, PC link | A |
| C | `homeassistant` key action run by the panel, and keys that follow an HA entity | B |

Not in scope: running ESPHome itself (YAML or its C++ framework), a Wi-Fi access point or captive portal, OTA over Wi-Fi, the HA web UI, Bluetooth.

---

## 0. What the code does today (constraints this design keeps)

- `main/main.cpp` owns USB: one task `ad_usb_console` (core 0, priority 1, 24 KB stack) reads lines of up to 1,099 bytes. It dispatches `AD_*` commands and pushes panel events (`deck_event`, `wake`, `brightness`, queued lines) by polling version counters in `deck_model`. ESP_LOG output goes to the same USB console, and the host ignores lines it does not know.
- `main/deck_model.c` is the single source of truth. Every accessor takes one FreeRTOS mutex and copies data in or out. The UI and other tasks never share pointers. Refresh is driven by version counters, never by callbacks into other tasks. Press events go into a 32-entry ring with monotonic ids, and `deck_model_events_since(cursor, …)` lets any number of readers keep their own cursor.
- NVS namespace `tessera` (16 KB `nvs` partition) holds the brightness. Writes are debounced (`brightness_save_soon`). The layout lives in SPIFFS `/store/layout.json`, with a `.bak` copy.
- Partitions fill the 16 MB flash completely (`ota_0` 6 MB, `ota_1` 6 MB, `storage` 0x3F0000). An app OTA cannot change the partition table, so **no stage may add a partition**.
- Internal RAM is scarce: `heap_caps_malloc_extmem_enable(16)` and LVGL buffers and stacks sit in PSRAM. The comment in `app_main` already reserves internal DMA heap "for the panel and SDIO driver".
- The host refuses any protocol that is not in `panel_serial.SUPPORTED_PROTOCOLS` (currently 1–4). Later features are announced as capability fields in `get_info`, as `ota` and `layoutSaved` already are.
- The editor backend (`tessera_app.py`) talks to the daemon (`tesserad.py`) through the files `deck-command.local.json` and `deck-runtime.local.json`, and the daemon serves a token-protected control API on 127.0.0.1 (`control_api.py`; its info file is made private).
- The panel holds only the **current page** (at most 18 keys). Without the PC it shows the last saved page and cannot change pages. Stages B and C accept this: offline HA keys work on the saved page.

---

## Stage A: Wi-Fi

### A.1 Components and build

`main/idf_component.yml` adds:

```yaml
  espressif/esp_wifi_remote: "^1.6.5"
  espressif/esp_hosted: ">=3.0.10"     # 3.0.3 fixed IDF 6.1 configure; 3.0.10 fixed SDIO timing options
```

`main/CMakeLists.txt`: add `wifi_service.c` and `wifi_config.c` to SRCS. Add `esp_wifi`, `esp_netif`, `esp_event` and `espressif__esp_wifi_remote` to REQUIRES.

`sdkconfig.defaults` adds the following. Symbol names marked (verify) come from the research at medium confidence and must be checked in `idf.py menuconfig` before merging:

```
CONFIG_ESP_HOSTED_HOST_TRANSPORT_BUS_SDIO=y
CONFIG_ESP_HOSTED_CP_TARGET_ESP32C6=y
CONFIG_ESP_HOSTED_P4_DEV_BOARD_FUNC_BOARD=y        # (verify) same pins as the Guition board
CONFIG_ESP_HOSTED_SDIO_SLOT_1=y
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_CLK=18
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_CMD=19
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_D0=14
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_D1=15
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_D2=16
CONFIG_ESP_HOSTED_HOST_SDIO_PIN_D3=17
CONFIG_ESP_HOSTED_HOST_SDIO_BUS_WIDTH_4=y
CONFIG_ESP_HOSTED_HOST_SDIO_CLK_KHZ=20000          # start at 20 MHz; 40 MHz only after a soak test passes
CONFIG_ESP_HOSTED_HOST_RESET_GPIO=54               # (verify) parked high since 3.0.9
CONFIG_ESP_HOSTED_HOST_SDIO_RX_STAGING_SLOTS=1
# CONFIG_ESP_HOSTED_HOST_SDIO_USE_MEMPOOL is not set  (or the PSRAM pool option, name to verify)
CONFIG_ESP_HOSTED_HOST_FEAT_WIFI=y
# CONFIG_ESP_HOSTED_SD_PWR_CTRL_LDO_INTERNAL_IO is not set   # LDO 4 belongs to the BSP SD slot
# Bluetooth off on both sides
```

Never enable native P4 Wi-Fi together with hosted (3.0.4 forbids it). Remote Wi-Fi options use the `WIFI_RMT_` prefix. `CONFIG_LWIP_TCP_MSS=400` is already set; leave it for stage A, because API messages are small, and measure before raising it.

**Flash budget:** run `idf.py size` before and after. lwIP, the Wi-Fi remote shim and ESP-Hosted add an estimated 0.5–0.9 MB; the 6 MB slot must keep at least 1 MB free for stages B and C.

**Co-processor firmware.** The C6 must run an ESP-Hosted co-processor image of the same major.minor version as the host component (ideally the same tag), built with IDF 6.1. The Guition factory image (network_adapter, 26 Aug 2025, IDF 5.5) has an unknown hosted version, and one owner reports it does not connect until reflashed. Stage A therefore reports the C6 version (`cp` field below) and does not treat a mismatch as fatal. Updating the C6 is stage A2 (A.9).

### A.2 Firmware module `main/wifi_service.c/.h`

One task, `tessera_wifi`, on core 1, priority 2, with a 4096-byte internal stack (measure with `uxTaskGetStackHighWaterMark`). Event handlers only post to the task's queue. All Wi-Fi calls run on that task.

```c
/* main/wifi_service.h */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "wifi_config.h"

typedef enum {
    WIFI_SVC_OFF = 0,        /* no credentials, or cleared */
    WIFI_SVC_CONNECTING = 1, /* bringing up the C6, associating, or waiting for DHCP; also while retrying */
    WIFI_SVC_CONNECTED = 2,  /* has an IPv4 address */
    WIFI_SVC_FAILED = 3,     /* gave up for now; `reason` says why; may retry later (see backoff) */
} wifi_svc_state_t;

typedef enum {
    WIFI_REASON_NONE = 0,
    WIFI_REASON_NO_COPROCESSOR, /* no INIT from the C6 within 15 s, or esp_wifi_init failed on the transport */
    WIFI_REASON_INIT,           /* esp_netif/esp_wifi setup failed for another reason */
    WIFI_REASON_NO_AP,          /* SSID not found */
    WIFI_REASON_AUTH,           /* wrong password (3 auth failures in a row) */
    WIFI_REASON_NO_IP,          /* associated but no DHCP lease within 30 s */
    WIFI_REASON_LOST,           /* was connected; reconnecting (state CONNECTING) */
    WIFI_REASON_CRASHED,        /* the boot guard turned Wi-Fi off after a crash during bring-up */
    WIFI_REASON_STORAGE,        /* NVS could not be read or written */
} wifi_svc_reason_t;

typedef struct {
    wifi_svc_state_t state;
    wifi_svc_reason_t reason;
    char ssid[WIFI_SSID_MAX + 1]; /* configured SSID, "" when none; never the password */
    char ip[16];                  /* dotted IPv4 when CONNECTED, else "" */
    int8_t rssi;                  /* dBm when CONNECTED, else 0; refreshed every 30 s */
    uint8_t mac[6];               /* station MAC from the C6, zero until known */
    char cp_version[16];          /* C6 ESP-Hosted version "2.7.0", "" until known */
} wifi_svc_status_t;

esp_err_t wifi_service_init(void);  /* call once after store_mount(); never blocks, never aborts */
/* Validated credentials (see wifi_config_from_json). Stores them, then connects (or reconnects). */
esp_err_t wifi_service_set(const wifi_credentials_t *credentials);
esp_err_t wifi_service_clear(void); /* erase credentials, stop Wi-Fi, state OFF */
void wifi_service_status(wifi_svc_status_t *out);
uint32_t wifi_service_version(void); /* bumped on every change of state, reason, ip or ssid; not on RSSI */
const char *wifi_service_state_name(wifi_svc_state_t state);   /* "off" "connecting" "connected" "failed" */
const char *wifi_service_reason_name(wifi_svc_reason_t reason); /* "" "no_coprocessor" "init" "no_ap" "auth" "no_ip" "lost" "crashed" "storage" */
/* Stage B uses this; stage A only defines it. */
bool wifi_service_connected(void);
```

```c
/* main/wifi_config.h: pure C (cJSON only), compiled into tests/native as well */
#pragma once
#include <stdbool.h>
#define WIFI_SSID_MAX 32
#define WIFI_PASSWORD_MAX 64
typedef struct {
    char ssid[WIFI_SSID_MAX + 1];
    char password[WIFI_PASSWORD_MAX + 1];
} wifi_credentials_t;
/* Parses {"ssid":"…","password":"…"}. On failure returns false and sets *field to "json", "ssid" or "password".
 * Wipes every copy of the password it made (also inside cJSON) before it returns. */
bool wifi_config_from_json(const char *json, wifi_credentials_t *out, const char **field);
void wifi_credentials_wipe(wifi_credentials_t *credentials); /* volatile memset */
```

**Validation rules (`wifi_config_from_json`):**

- The input must be a JSON object. Unknown keys are ignored. `ssid` and `password` must be strings.
- `ssid`: 1–32 bytes after JSON decoding (UTF-8, as cJSON decodes `\uXXXX`, surrogate pairs included), with no NUL and no control character below 0x20.
- `password`: `""` (open network), or 8–63 printable ASCII characters (0x20–0x7E), or exactly 64 hex digits (a raw PSK). Anything else is `password`.
- Before `cJSON_Delete`, the parser overwrites the `password` item's `valuestring` with zeros. The caller zeroes the line buffer after the command.

**Storage.** NVS namespace `tessera_net` (new, so `AD_WIFI_CLEAR` never touches `tessera`). Stage B keeps its `api_*` keys here too, so `AD_WIFI_CLEAR` erases only the three keys below, never the whole namespace:

| Key | Type | Meaning |
|---|---|---|
| `ssid` | str | ≤32 bytes |
| `pass` | str | ≤64 bytes |
| `boot_guard` | u8 | bring-up crash guard, see below |

`esp_wifi_set_storage(WIFI_STORAGE_RAM)` is called before `esp_wifi_set_config`, so the credentials are never stored on the C6. A write commits only when the value changed.

**Bring-up sequence (on the `tessera_wifi` task, only when credentials exist):**

1. `wifi_service_init()` (from `app_main`, after `store_mount()` and before the UI starts) loads NVS and creates the task. **With no credentials it stops there: the hosted stack, the SDIO bus and GPIO54 are never touched.** That is why Wi-Fi is off by default and a panel without a C6 behaves exactly as today.
2. The task waits 3 s after boot, so USB and the UI are up first and a hung bring-up cannot delay the handshake.
3. Boot guard: if `boot_guard` is 1 and the reset reason is `panic`, `int_wdt`, `task_wdt` or `wdt`, the previous bring-up crashed the panel. The task sets FAILED/`crashed`, clears `boot_guard` and stops; only a new `AD_WIFI_SET` tries again. Otherwise it writes `boot_guard=1`.
4. `esp_netif_init`, `esp_event_loop_create_default` (accept `ESP_ERR_INVALID_STATE`), `esp_netif_create_default_wifi_sta`, set the hostname (`tessera-XXXXXX`, from the last 3 MAC bytes in lowercase hex; stage B replaces it with the device name), `esp_wifi_init(WIFI_INIT_CONFIG_DEFAULT())`. This call brings up ESP-Hosted. If it fails, or no INIT event arrives within 15 s (a one-shot timer posts a timeout to the queue), the state is FAILED/`no_coprocessor`. The task then stays parked without retrying and leaves the C6 alone until the next `AD_WIFI_SET` or reboot.
5. `boot_guard=0` once `esp_wifi_init` returned.
6. Read the C6 version (`esp_hosted_get_coprocessor_fwversion` or the 3.x equivalent, verify the name) into `cp_version`. A different major.minor than the host component logs one warning, and the field shows it.
7. `esp_wifi_set_storage(RAM)`, `esp_wifi_set_mode(WIFI_MODE_STA)`, `esp_wifi_set_config` (threshold `WIFI_AUTH_WPA2_PSK`, or `WIFI_AUTH_OPEN` when the password is empty; `pmf_cfg.capable = true`), `esp_wifi_set_ps(WIFI_PS_NONE)` (reported to fix boot delays on this board), `esp_wifi_start`, then `esp_wifi_connect` on `WIFI_EVENT_STA_START`.
8. `IP_EVENT_STA_GOT_IP` sets CONNECTED, the IP and the RSSI (`esp_wifi_sta_get_rssi`).

**Reconnect and backoff:**

- On `WIFI_EVENT_STA_DISCONNECTED`, the state is CONNECTING/`lost` (it was connected) or keeps CONNECTING. Retry after 2, 4, 8, 16, 32, then 60 s (cap), with ±20 % jitter. The delay resets on GOT_IP.
- Auth reasons (`WIFI_REASON_AUTH_FAIL`, `4WAY_HANDSHAKE_TIMEOUT`, `HANDSHAKE_TIMEOUT`, `AUTH_EXPIRE`, `ASSOC_FAIL` with a wrong key) three times in a row give FAILED/`auth`, with a retry every 5 min. The router may block a client that keeps guessing, and the password is most likely just wrong.
- `NO_AP_FOUND` three times in a row gives FAILED/`no_ap`, retrying on the 60 s cap.
- Associated but no IP within 30 s gives FAILED/`no_ip`, then disconnect and back off.
- `wifi_service_set` while running: `esp_wifi_disconnect`, new config, connect, backoff reset. `wifi_service_clear`: `esp_wifi_stop` (the stack stays initialized; a deinit/init cycle over hosted is not trusted), erase `ssid`, `pass` and `boot_guard` (not the API key), state OFF.

**Coexistence.** The service never calls LVGL or the USB driver. It mirrors its status into `deck_model` for the UI (A.4). The console task polls `wifi_service_version()` for the unsolicited line. A failing C6 can only make Wi-Fi unavailable: no `ESP_ERROR_CHECK` on any Wi-Fi or hosted call, and every error becomes a state.

**Logging.** The service may log the SSID, state changes, reasons, the IP, the C6 version and DMA heap free before and after bring-up (`heap_caps_get_free_size(MALLOC_CAP_DMA)`). It never logs the password, the line that carried it, or `wifi_config_t`.

### A.3 Serial protocol 5

`main/protocol_version.h`: `#define TESSERA_PROTOCOL 5` with the comment line `5 = adds Wi-Fi (AD_WIFI_SET, AD_WIFI_CLEAR, AD_WIFI_STATUS, {"type":"wifi"}) and the "wifi" field in get_info`. Stages B and C do not bump the protocol: they add the capability fields `api` and `ha` in `get_info`, following the convention in that header.

`main.cpp` dispatches `AD_WIFI_` before the JSON branch, the same way `AD_OTA_` is dispatched. It calls `static void wifi_command(char *line)`, then runs `memset(line, 0, sizeof(line))`.

| Host to panel | Answer |
|---|---|
| `AD_WIFI_SET <json>`, where `<json>` is `{"ssid":"…","password":"…"}` | `AD_WIFI_SET OK`, or `AD_WIFI_SET INVALID <field>` with `<field>` one of `json`, `ssid`, `password`, or `AD_WIFI_SET FAILED storage` |
| `AD_WIFI_CLEAR` | `AD_WIFI_CLEAR OK` or `AD_WIFI_CLEAR FAILED storage` |
| `AD_WIFI_STATUS` | one `{"type":"wifi",…}` line (below) |

Rules:

- Exactly one space after the command word. The JSON is the rest of the line. The whole line is at most 1,099 bytes; a longer one is dropped without an answer, as today. The host sends `json.dumps({...}, ensure_ascii=True, separators=(',', ':'))`, so the line is pure ASCII: at most 32 code points × 12 bytes (a surrogate pair is 12 bytes, so this bounds any SSID) plus 64 × 2 bytes for the password plus the frame stays under 600 bytes.
- `OK` means stored and a connect has started, not that it is connected. The result arrives as `{"type":"wifi"}` lines.
- No answer ever echoes the SSID or the password, apart from the SSID in status lines.
- On protocol-4 firmware these lines are unknown and get no answer. The host never sends them there (A.5).

**Status line (`AD_WIFI_STATUS`, and unsolicited):**

```json
{"type":"wifi","state":"connected","ssid":"HomeNet","ip":"192.168.1.40","rssi":-58,"mac":"AA:BB:CC:DD:EE:FF","cp":"2.7.0"}
{"type":"wifi","state":"failed","reason":"auth","ssid":"HomeNet"}
{"type":"wifi","state":"off"}
```

- `state` is always present. `ssid` appears when credentials are stored. `ip` and `rssi` appear only when the state is `connected`. `reason` appears only when it is not none. `mac` and `cp` appear once known. Built with cJSON, so the SSID is escaped correctly.
- Unsolicited: the console task sends this line when `wifi_service_version()` changed since it last sent one, at most once a second (the last change wins). An RSSI change alone does not send a line.
- `get_info` gains `"wifi":"off|connecting|connected|failed"`. With the protocol number, this field tells the host that `AD_WIFI_*` exists.

PROTOCOL.md gets the three commands, the status line, the `wifi` handshake field and a Wi-Fi section. RELEASING.md gets the version 5 line.

### A.4 Panel UI: About sheet

`deck_model` gains a small network record, so `ui.cpp` stays free of Wi-Fi headers and the native build keeps working:

```c
typedef struct {
    uint8_t state;   /* wifi_svc_state_t values */
    uint8_t reason;  /* wifi_svc_reason_t values */
    char ssid[33];
    char ip[16];
    int8_t rssi;
    bool api_client; /* stage B: a Home Assistant client is connected */
} deck_network_t;
void deck_model_set_network(const deck_network_t *network);
void deck_model_network(deck_network_t *out);
uint32_t deck_model_network_version(void);
```

`wifi_service` calls `deck_model_set_network` on every change and on every RSSI refresh. The About sheet (long press on the logo) gains one line under *PC connected*. It is refreshed by the existing UI timer when `deck_model_network_version()` changes. The card grows from 300 to 336 px, and *Brightness* and the slider move down 34 px. ASCII only (the DejaVu subsets may lack `·` and `−`):

| State | Text | Color |
|---|---|---|
| off | `Wi-Fi off` | Soft |
| connecting | `Wi-Fi: connecting to HomeNet` | Soft |
| connected | `Wi-Fi: 192.168.1.40, -58 dBm` | Accent |
| failed | `Wi-Fi: wrong password` / `network not found` / `no address` / `no Wi-Fi chip` / `turned off after a crash` / `setup failed` | Amber |

The rail's *NO PC* label stays as it is; it is about USB.

### A.5 Host

**`panel_serial.py`:**

```python
SUPPORTED_PROTOCOLS = (1, 2, 3, 4, 5)
WIFI_PROTOCOL = 5
WIFI_STATES = ('off', 'connecting', 'connected', 'failed')
WIFI_REASONS = ('no_coprocessor', 'init', 'no_ap', 'auth', 'no_ip', 'lost', 'crashed', 'storage')

def wifi_line(ssid: str, password: str) -> str:
    """'AD_WIFI_SET {"ssid":…,"password":…}'. Raises ValueError on the same rules as the firmware."""

def check_wifi_credentials(ssid: str, password: str) -> None:  # ValueError('ssid: …') / ValueError('password: …')

def parse_wifi_status(message: dict) -> dict | None:
    """A {"type":"wifi"} line reduced to {state, reason?, ssid?, ip?, rssi?, mac?, cp?}, or None when malformed."""

class PanelSerial:
    wifi_done: threading.Event   # set by the reader loop on an 'AD_WIFI_' line
    wifi_reply: str
    def supports_wifi(self) -> bool:            # self.info['protocol'] >= WIFI_PROTOCOL
    def wifi_set(self, ssid, password) -> None: # holds write_lock, sends, waits 4 s for AD_WIFI_SET; OSError(reply) unless OK
    def wifi_clear(self) -> None:
    def wifi_status(self) -> None:              # sends AD_WIFI_STATUS; the answer arrives as an event
```

`wifi_set` raises `RuntimeError('The panel firmware does not support Wi-Fi; update it (protocol 5)')` when `supports_wifi()` is false. It never logs the line. The password exists only in the arguments and the encoded bytes.

**`tesserad.py`:**

- The `reader_loop` routes `AD_WIFI_SET `, `AD_WIFI_CLEAR ` replies to `panel.wifi_reply`/`wifi_done`. On `{"type":"wifi"}` it stores `parse_wifi_status(message)` in `self.wifi` and forces a runtime publish.
- After the handshake, if `supports_wifi()`, it sends `AD_WIFI_STATUS` once.
- `publish_runtime` adds `'wifi': self.wifi` (state, reason, ssid, ip, rssi, cp, never a password) and leaves `'protocol'` as is.
- The verbose `Panel: …` log is unchanged: the panel never sends a password back.

**`control_api.py`:** a new route `wifi`, for the **owner token only**. `check_scope` refuses it to every plugin grant, even one listing it, because `Grant.routes` for plugins is built from a fixed list that never includes `wifi`.

```
POST /v1/wifi {"do":"set","ssid":"…","password":"…"}  -> 200 {"wifi":{…status…}}
POST /v1/wifi {"do":"clear"}                          -> 200 {"wifi":{…}}
POST /v1/wifi {"do":"status"}                         -> 200 {"wifi":{…}}  (also sends AD_WIFI_STATUS)
409 {"error":"The panel is not connected"} / {"error":"The panel firmware does not support Wi-Fi; update it"}
400 {"error":"ssid: …"} / {"error":"password: …"}
```

The handler runs on the HTTP thread and calls `panel.wifi_set` directly. It does **not** go through the job queue, so the password never lands in a job tuple that an error path could log. `audit()` logs only the method, path and status code, as it does today.

**`tessera_app.py`** (editor backend): a new command `panel-wifi` with the same body. It reads the daemon's port and owner token from `deck-api.local.json` and posts to `/v1/wifi`. **It never writes `deck-command.local.json` for Wi-Fi**, because that file would put the password on disk. `status()` passes `runtime['wifi']` through to the editor.

**Config (`profiles.json`):**

```json
"panel": { "wifi": { "ssid": "HomeNet" } }
```

- Only the SSID: the last network sent from this PC. It pre-fills the dialog and lets the editor say "the panel is on another network". **The password is never stored on the PC.** The panel keeps it in NVS, and to move to another network the user types it once in the dialog. Nothing on the PC needs it later. Storing it would put a Wi-Fi password into profiles.json, its backups and exported configs.
- Saving a config never sends anything to the panel. Only the dialog's *Connect* button does.
- `config_check._check_panel`: allow the key `wifi`. It must be an object with only `ssid`, a string of 1–32 UTF-8 bytes without control characters. Error: `panel.wifi.ssid must be 1-32 bytes of text`.
- `diagnostics.py`: `panel.wifi.ssid` is replaced with `<ssid>`, and the runtime `wifi.ssid`, `ip` and `mac` are replaced the same way (`clean()`, and the config summary).
- `import_review.py`: an imported `panel.wifi` is kept (harmless) and never triggers a send.

### A.6 Editor dialog: Panel, then *Wi-Fi and Home Assistant*

In `index.html`, a `<dialog id="wifi-dialog">` opened from the Panel menu next to *Firmware*. The code goes in `dialogs.js` (`openWifi`, `refreshWifi`, `sendWifi`, `forgetWifi`):

- **Status line** from `dashboard.device.wifi`, polled every 2 s while the dialog is open: `Connected to HomeNet · 192.168.1.40 · -58 dBm · C6 2.7.0`, `Connecting…`, `Wrong password`, `No Wi-Fi chip answered (the C6 may need new firmware)`, `Wi-Fi is off`.
- **Fields**: Network name (`text`, `maxlength` 32 bytes, checked in JS with `new TextEncoder()`), pre-filled from the status SSID, then `panel.wifi.ssid`. Password (`type=password`, `autocomplete="off"`, a show toggle, an *Open network (no password)* checkbox).
- **Buttons**: *Connect* runs `api('command/panel-wifi', {do:'set', ssid, password})`, then clears the password field and the JS variable, then saves `panel.wifi.ssid` through `savePanel`. *Forget Wi-Fi* sends `{do:'clear'}` after a confirm.
- **Gating**: with no panel connected the form is disabled with *Connect the panel over USB*. With `device.protocol < 5` it is disabled with *Update the panel firmware to use Wi-Fi* and a button that opens the firmware dialog.
- The Home Assistant part (stage B) is a second section in the same dialog, hidden while `device.api` is absent.
- Accessibility follows the existing dialogs: labels, focus returns to the menu, Escape closes, and the axe smoke test passes.

### A.7 Stage A tests

Native (`tests/native`, add `main/wifi_config.c` to `test_ui`'s sources):

- `wifi_config_from_json`: valid ASCII; `æ` and a surrogate pair decoded to UTF-8; 32-byte SSID ok and 33 rejected; empty SSID rejected; control character rejected; password lengths 0 ok, 7 rejected, 8 and 63 ok, 64 hex ok, 64 non-hex rejected, non-ASCII rejected; missing or non-string fields; not an object; the `field` value for each failure; the password buffer zeroed by `wifi_credentials_wipe`.
- `deck_model_set_network`/`deck_model_network` copy and version bump. `render_screens` writes the About sheet in all four states for visual review.

Host (`tests/test_wifi.py`, fake serial as in `test_handshake.py`):

- A protocol-5 handshake is accepted and `supports_wifi()` is true; on protocol 4 `wifi_set` raises without writing to the port.
- `wifi_line` produces exact bytes (ASCII, compact) and rejects what the firmware rejects (same table as the native tests).
- The reply wait: `OK`, `INVALID password` raises with that text, and a timeout raises.
- `{"type":"wifi"}` parsing (valid, unknown state, extra fields, wrong types) and the runtime file holding `wifi` without a password.
- **Leak tests**: after a `wifi_set` with a canary password, the canary appears in none of the host log, `deck-runtime.local.json`, `profiles.json`, a diagnostics bundle, or the control API audit log.
- Control API: the owner gets 200, a plugin grant gets 403, a missing panel gets 409.
- `config_check`: `panel.wifi` valid and invalid, unknown keys under `panel.wifi`.
- Editor smoke (`tests/editor_smoke`): the dialog opens, is disabled on protocol 4, passes axe and gives focus back.

Hardware (by the user, not CI): `tests/hardware_smoke.py --wifi` asks for the password with `getpass` (never from a file or argument), sends `AD_WIFI_SET`, waits up to 30 s for `connected`, and prints the IP, RSSI, C6 version and `heap` before and after. It then checks that keys, layout push and OTA still answer, runs `AD_WIFI_CLEAR` and checks `off`. A second run with the C6 held in reset (or with a wrong SSID) must show `failed` while every USB function keeps working.

### A.8 Stage A done when

- Without credentials, the boot, the handshake, the memory figures (±1 KB internal) and every USB function behave as before.
- With credentials and a working C6, the panel connects within 15 s of boot and reconnects after an AP reboot.
- With a missing or incompatible C6 the panel boots normally and shows `no Wi-Fi chip`. After a crash during bring-up, the next boot shows `turned off after a crash` and works over USB.

### A.9 Stage A2 (optional): update the C6 over USB

No partition is free, so the image streams from USB straight into `esp_hosted_slave_ota_begin/write/end/activate`. It needs a working SDIO link, i.e. an old but answering C6. The commands mirror `AD_OTA_*`: `AD_CP_OTA_BEGIN <bytes> <sha256>`, `AD_CP_OTA_DATA <offset> <hex>` (≤512 bytes, acknowledged every 2 KB), `AD_CP_OTA_END`, `AD_CP_OTA_ABORT`. The capability field is `"cpOta":1`. The firmware package carries `network_adapter_esp32c6.bin` built from the same ESP-Hosted tag, and the firmware dialog offers *Update Wi-Fi chip* when `cp` differs from the bundled version. A C6 that does not answer at all needs the wired UART route described in INSTALL.md.

---

## Stage B: ESPHome native API server

Advertised in `get_info` as `"api":1`. Off until the user turns it on in the dialog. It runs only while Wi-Fi is connected.

### B.1 Module layout (`main/api/`)

| File | Job | Native-testable |
|---|---|---|
| `api_proto.c/.h` | Hand-written protobuf writer and reader: varint, zigzag (`pb_zigzag32`, for the sint32 fields of `ParsedTimezone`), fixed32, float, bool, length-delimited; field iterator; message id constants | yes |
| `api_messages.c/.h` | Encode and decode only the messages listed in B.4, into C structs with fixed-size strings | yes |
| `api_noise.c/.h` | `Noise_NNpsk0_25519_ChaChaPoly_SHA256` responder: SymmetricState, CipherState, HKDF, MixHash/MixKey/MixKeyAndHash, split; ESPHome framing | yes, with mbedTLS built from `$IDF_PATH` |
| `api_crypto.c/.h` | The only file that calls crypto: X25519, ChaCha20-Poly1305 (IETF, 96-bit nonce), SHA-256, HMAC-SHA256, random | target; native uses the same mbedTLS sources |
| `api_session.c/.h` | Per-connection state machine: Noise hello, handshake, Hello, DeviceInfo, ListEntities, SubscribeStates, ping/keepalive, disconnect, command dispatch | yes (with a null cipher) |
| `api_entities.c/.h` | Entity table, FNV-1 keys, state snapshots from `deck_model`, commands to `deck_model` | yes |
| `api_server.c/.h` | lwIP socket listener on 6053, `select()` loop, connection slots, timeouts, the `tessera_api` task | target |
| `api_mdns.c` | `espressif/mdns` hostname and service with TXT records | target |
| `press_router.c/.h` | Reads deck events with its own cursor, classifies press/hold/double, feeds the event entities (B) and the HA action runner (C) | yes |

**Why hand-written protobuf instead of nanopb:** about 25 messages with flat fields of wire types 0, 2 and 5. nanopb needs `protoc` and a Python generator in the firmware build, plus callbacks or `max_size` options for strings. A writer and reader of about 250 lines is easier to audit and to fuzz natively. Golden bytes for every message come from the real `api.proto`, generated on the PC by `tools/gen_api_fixtures.py` from `aioesphomeapi`'s `api_pb2` into `tests/fixtures/esphome_api/*.hex`.

**Why own Noise on mbedTLS instead of noise-c:** NNpsk0 with one cipher suite is about 300 lines, and noise-c is large and not maintained. ESP-IDF 6.x ships mbedTLS 4 with the PSA Crypto API, so `api_crypto.c` uses PSA: `psa_raw_key_agreement(PSA_ALG_ECDH, …)` on a `PSA_ECC_FAMILY_MONTGOMERY` 255-bit key, `psa_aead_encrypt/decrypt(PSA_ALG_CHACHA20_POLY1305)`, `psa_hash_compute(PSA_ALG_SHA_256)` and `psa_mac_compute(PSA_ALG_HMAC(PSA_ALG_SHA_256))`. Verify that X25519 and ChaChaPoly are enabled in the IDF 6.1 mbedTLS Kconfig (`CONFIG_MBEDTLS_ECP_DP_CURVE25519_ENABLED`, `CONFIG_MBEDTLS_CHACHAPOLY_C` or their PSA_WANT forms). If they are not, the fallback is vendoring Monocypher (`crypto_x25519`, `crypto_chacha20_ietf` + `crypto_poly1305`) behind the same `api_crypto.h`. The test vectors are the Cacophony/snow vectors for `Noise_NNpsk0_25519_ChaChaPoly_SHA256`, and ESPHome's prologue `"NoiseAPIInit\0\0"` is checked against aioesphomeapi.

**Task and memory.** `tessera_api` runs on core 1, priority 3, with a 10 KB internal stack (X25519 and the HKDF need a few KB; back to 8 KB once the on-device high-water mark, logged at debug level on every close, shows more than 2 KB free). The task is created only while the API is on and Wi-Fi is connected, and deletes itself after 30 s without them; the PSRAM buffers stay for the next start. Four connection slots (ESPHome itself allows 8), each with four 1,536-byte buffers in PSRAM. The largest message we accept is 1,024 bytes; a larger declared size closes the connection (we never need ESPHome's 32 KB). Handshake frames are limited to 128 bytes. When all slots are busy, a new connection may replace only the oldest pending slot from its own IP address, or a ready slot silent for 30 s; otherwise the new connection is closed, so a flood never evicts a live HA session. Closes before Hello log at debug level only.

### B.2 Wire behavior

- Port 6053. **Noise only.** A first byte of `0x00` (a plaintext client) gets the plaintext frame `00` + varint size + varint type `0` + `"Bad indicator byte"` and a close, which aioesphomeapi reports as `RequiresEncryptionAPIError`. A first byte other than `0x01` is closed at once.
- Handshake: the client hello `01 00 00`, then the server hello `01` + name + `00` + MAC (`AA:BB:CC:DD:EE:FF`) + `00`, then the client's `e` (48 bytes in a `00`-prefixed frame), then the server's `e, ee` + tag. On a MAC failure the server sends a frame with first byte `01` + `"Handshake MAC failure"` and closes. HA relies on this to show *invalid key*, and its probe with a wrong PSK relies on it to read the name.
- Data frames: `01` + BE16 length + ciphertext of (BE16 type, BE16 length, protobuf). Nonces count up per direction and are never reused. A counter reaching 2^32 closes the connection.
- Timeouts: 10 s to finish the handshake and `HelloRequest` (ESPHome uses 60 s; ours is shorter on purpose). Keepalive: we send `PingRequest` after 20 s of silence and close after 50 s without any frame.
- Writes have a 250 ms send timeout and one second in all per frame, so a client that stops reading cannot hold the task.
- Hello: answer `api_version` 1.12, `server_info` `"Tessera <firmware version>"`, `name` = the device name. (1.12 is enough for the entity types here; if HA's integration asks for a newer minor, raise it, after checking which fields that minor adds.) Password auth (ids 3/4) is gone in current ESPHome; a `ConnectRequest` (3) still gets a `ConnectResponse` (4) with `invalid_password=false` for older clients.

### B.3 Identity, key and mDNS

- **Device name** (`name`, ESPHome rules `^[a-z0-9-]{1,31}$`, also the DHCP and mDNS hostname): from `panel.homeassistant.name`, default `tessera-deck`. **Friendly name**: `panel.homeassistant.friendly_name`, default `Tessera Deck`. Optional `area`.
- **DeviceInfoResponse**: `uses_password=false`, `name`, `mac_address`, `esphome_version="2026.11.0"` (a compatible version string, since HA shows it and some features gate on it; the real firmware version goes into `project_version`), `compilation_time` from the app description, `model="Guition JC1060P470C"`, `manufacturer="Tessera"`, `friendly_name`, `suggested_area`, `project_name="catorendal-a11y.tessera-deck"`, `project_version=<firmware version>`, `api_encryption_supported=true`, `webserver_port=0`.
- **Encryption key**: 32 bytes from `esp_fill_random`, made on the panel the first time the API is turned on and stored as NVS blob `tessera_net/api_psk`. It never leaves the panel except over USB on request (B.6). There is no zero-PSK provisioning mode.
- **mDNS** (`espressif/mdns`, started on GOT_IP, stopped on disconnect or when the API is turned off): the hostname is the device name. Service `_esphomelib._tcp`, port 6053, instance name = the device name. TXT records: `friendly_name`, `version` (same as `esphome_version`), `mac` (12 lowercase hex, mandatory for HA), `platform=ESP32`, `board=esp32-p4`, `network=wifi`, `project_name`, `project_version`, `api_encryption=Noise_NNpsk0_25519_ChaChaPoly_SHA256`. Multicast through the C6 bridge is unverified: the stage B hardware test checks it with `dns-sd -B _esphomelib._tcp` from Windows, and manual add by IP in HA is the documented fallback.

### B.4 Messages handled

| Id | Message | Direction |
|---|---|---|
| 1/2 | Hello request/response | C→S / S→C |
| 3/4 | Connect (legacy, always accepted) | C→S / S→C |
| 5/6 | Disconnect request/response | both |
| 7/8 | Ping request/response | both |
| 9/10 | DeviceInfo | C→S / S→C |
| 11, 19 | ListEntities, Done | C→S, S→C |
| 12, 15, 16, 52, 61, 107 | ListEntities BinarySensor, Light, Sensor, Select, Button, Event | S→C |
| 20 | SubscribeStates | C→S |
| 21, 24, 25, 53 | BinarySensor, Light, Sensor, Select state | S→C |
| 108 | Event | S→C |
| 32, 54, 62 | Light, Select, Button command | C→S |
| 36/37 | GetTime request (sent by us) / response | S→C / C→S |
| 34, 35 | Subscribe HA services / HomeassistantActionRequest (stage C) | C→S / S→C |
| 38, 39, 40 | Subscribe HA states / our subscription / HA state (stage C) | C→S / S→C / C→S |

Any other id is ignored. `SubscribeLogs` (28) is ignored too, so logs never leave over Wi-Fi.

### B.5 Entity model

Keys are the FNV-1 32-bit hash of `object_id` (offset basis 2166136261, prime 16777619), so HA's unique ids stay stable across firmware versions. No entity depends on the page: key entities are per slot.

| object_id | Type | Details |
|---|---|---|
| `key_1` … `key_18` | event | name `Key N`, `device_class` `button`, `event_types` `["press","hold","double"]`. Sent on a key press (B.7). Disabled by default for slots 13–18. |
| `profile` | select | name `Profile`, options from the host (B.6). State = `deck_model_context().profile`, or `missing_state` when the panel has no list. |
| `page` | select | name `Page`, the pages of the current profile, same rules. |
| `backlight` | light | name `Backlight`, `supported_color_modes` `[BRIGHTNESS]`. `state` = not dimmed, `brightness` = level / 100. |
| `wifi_signal` | sensor | name `Wi-Fi signal`, unit `dBm`, `device_class` `signal_strength`, `state_class` measurement, `entity_category` diagnostic, 0 decimals, sent every 60 s and on connect. |
| `show_clock` | button | name `Show clock`, icon `mdi:clock-outline`. |
| `pc_connected` | binary_sensor | name `PC connected`, `device_class` `connectivity`, from `deck_model_host_linked(3500)`, checked every second and sent on change. |

**Commands:**

- `backlight`: `has_state && !state` gives `deck_model_set_dimmed(true)` and backlight 0, done by the console task through a new request flag (it already owns the backlight). `state`/`brightness` gives `deck_model_request_brightness(round(b*100) clamped 1..100, save=true)`, then the existing path applies it, debounces the NVS write and sends `{"type":"brightness","level":N}` to the PC, so the host's stored level follows.
- `show_clock`: `deck_model_request_screen(DECK_SCREEN_AMBIENT)`.
- Select and button commands closer than 250 ms to the last one from the same client are dropped (a select gets its state back), and a select of the current value queues nothing, so a flood cannot push the PC's touch lines out of `deck_model_queue_line`. Light commands are not limited: they are latest-wins requests, and dropping one would lose the end of a slider drag.
- `profile`/`page` select: valid only while the PC is linked. The panel queues `{"type":"ha_select","what":"profile"|"page","value":"…"}` via `deck_model_queue_line`, and the host validates it and switches as a rail shortcut does. When the PC is not linked, or the value is not in the options, the panel answers with the current state again so HA's dropdown snaps back.
- No entity can press a key or run a PC action. This is deliberate: the network side can never reach the PC's hotkeys, shell or programs.

**Time without the PC:** after `SubscribeStates`, if the clock was never set by `AD_TIME` in this boot (or the PC is not linked), the panel sends `GetTimeRequest`. It applies `epoch_seconds` with a new `time_service_set_unix(int64_t epoch, const char *posix_tz)`. Verified against api.proto (dev, 2026-11): field 2 `timezone` is deprecated since ESPHome 2026.9 and current firmware reads only field 3 `parsed_timezone` (`ParsedTimezone`: sint32 `std_offset_seconds`, sint32 `dst_offset_seconds`, `DSTRule dst_start`, `dst_end`; `DSTRule`: sint32 `time_seconds`, `day`, `type` none/month-week-day/Julian/day-of-year, `month`, `week`, `day_of_week`). Offsets are POSIX style (positive west, esphome `time/posix_tz.h`). The panel builds a POSIX string from field 3 (`STD-1DST-2,M3.5.0,M10.5.0/3`), falls back to field 2 only when it has a POSIX shape, and otherwise keeps UTC and logs that. Epochs past 2100 and TZ characters outside `[A-Za-z0-9<>+,.:/ -]` are refused. This is repeated every 6 h while the PC is absent. `AD_TIME` from the PC always wins.

### B.6 Host and serial additions (capability `"api":1`)

| Host to panel | Answer |
|---|---|
| `AD_API_SET {"enabled":true,"name":"tessera-deck","friendly":"Tessera Deck","area":""}` | `AD_API_SET OK` or `AD_API_SET INVALID <field>` |
| `AD_API_KEY` | `AD_API_KEY <44 characters of base64>` (creates the key if none exists) |
| `AD_API_KEY NEW` | `AD_API_KEY <base64>`; also closes all API connections |
| `AD_API_OPTIONS {"profiles":["…"],"pages":["…"]}` | `AD_API_OPTIONS OK` or `INVALID` (at most 16 entries each, at most 31 bytes each) |
| `AD_API_STATUS` | `{"type":"api","enabled":true,"clients":1,"ha":true,"name":"tessera-deck"}`, also sent unsolicited on change |

- Settings are stored in `tessera_net` as `api_on` (u8), `api_name` (str), `api_friendly` (str) and `api_area` (str). The options are RAM only, and the host sends them after every handshake and whenever the profile list or page changes.
- `"ha":true` means a client completed Hello and `SubscribeStates`. `deck_network_t.api_client` mirrors it, and the About sheet adds `Home Assistant: connected` / `waiting` / `off`.
- Config: `panel.homeassistant = {"enabled": bool, "name": "tessera-deck", "friendly_name": "Tessera Deck", "area": ""}`. `config_check` checks the name against `^[a-z0-9-]{1,31}$`, `friendly_name` 1–60 characters, `area` 0–40 characters, and no other keys. The host sends `AD_API_SET` after a handshake when the config differs from what the panel reported, and on save.
- Dialog, *Home Assistant* section: an *Enable* switch, the name fields, the status line, and the encryption key, hidden until *Show key*, with *Copy* and *Make new key* (with a confirm that HA must get the new key). Short steps: *In Home Assistant: Settings, Devices & services, ESPHome, Add. Paste this key.* The key is fetched with `api('command/panel-api', {do:'key'})` through the same owner-only control API route pattern (`/v1/api`). It is shown, never saved by the host, and never written to logs, runtime or diagnostics.
- The daemon's `reader_loop` handles `{"type":"ha_select"}` by validating it against the config, then switching profile or page. It handles `{"type":"api"}` into `runtime['api']`.

### B.7 Press routing and locks

- `press_router` runs inside `tessera_api` and reads `deck_model_events_since(cursor, …)` with its own cursor, exactly as the USB console does. The USB path is not changed in any way: the PC still gets every `deck_event` and does its own double detection.
- Classification for the API: an event with `hold` gives `hold`. A key whose layout has `double:true` waits 350 ms; a second press on the same key in that window gives one `double`, otherwise one `press`. A key without `double` gives `press` at once.
- If the ring wraps (more than 32 events between two polls; it polls every 20 ms), the missed events are dropped and logged once.
- **Locks**: the API task touches only `deck_model` accessors (one mutex, copy in/out), `wifi_service_status`, and the request/take pairs that the console task or the LVGL timer already consume (`request_brightness`, `request_screen`, `set_dimmed`, `queue_line`, `request_feedback`). It never takes the LVGL lock and never writes to USB. `deck_model_note_host()` is called only by USB lines, so `PC connected` stays truthful. The panel lock (`AD_PANEL_LOCK`) blocks touches only. HA commands still work while it is locked, because the lock is about fingers on the screen.
- NVS: the API writes only on `AD_API_*` commands and on key creation. Brightness from HA goes through the existing debounced save.

### B.8 Stage B tests

- Native: protobuf writer and reader against the golden fixtures (every message in B.4, both directions), plus a fuzz loop of 100k random buffers into the reader (no crash, no out-of-bounds; built with `-fsanitize=address,undefined`). Noise: the Cacophony vectors, plus a full handshake against a test initiator in the same process. Also a wrong PSK gives the exact reject frame, and nonce and tag checks hold. Session: Hello → DeviceInfo → ListEntities order and Done, SubscribeStates sends one state per stateful entity, an unknown id is ignored, the oversized frame and the handshake timeout close. Entities: FNV-1 keys for all object_ids (fixed values in the test), `press_router` press/hold/double timing.
- Host: `AD_API_*` parsing, options sent on handshake and profile change, `ha_select` validation (an unknown profile is ignored), `panel.homeassistant` checks, the key never in logs or runtime (canary test), owner-only routes.
- PC test script `tools/esphome_api_check.py` (run by the user against a real panel; uses `aioesphomeapi` from a separate venv, not `host/requirements.txt`). It takes `--host`, `--key` (or `TESSERA_API_KEY` from the environment; never a file in the repo):
  1. A plaintext connect must raise `RequiresEncryptionAPIError`, and a wrong key `InvalidEncryptionKeyAPIError`.
  2. `device_info()`: name, MAC matching USB `AD_WIFI_STATUS`, `project_name == "catorendal-a11y.tessera-deck"`.
  3. `list_entities_services()` must return exactly the B.5 set with the expected keys.
  4. `subscribe_states`: the initial states arrive; set the backlight to 30 % and back, and see the light state follow; press `show_clock` (the user sees the clock); wait for a `key_N` event while the user taps a key, then hold it, then double-tap it.
  5. 50 connect/disconnect cycles, then a 1-hour idle soak with pings. The user reads `heap` over USB before and after (no leak above 2 KB).
  6. mDNS: browse `_esphomelib._tcp` and check the TXT `mac` and `api_encryption`.
- Real HA: add through discovery, enter the key, check entities, restart HA and the panel, change the IP (DHCP), then pull the USB cable while HA stays connected.

---

## Stage C: Home Assistant keys

Capability `"ha":1` in `get_info`. Needs `"api":1`.

### C.1 Action type `homeassistant`

Config (in `actions`, `hold_actions` or `double_actions`):

```json
{"type": "homeassistant", "action": "light.toggle", "entity_id": "light.kitchen", "data": {"brightness_pct": "50"}}
```

- `ACTION_FIELDS['homeassistant'] = 'action'`.
- `_check_homeassistant`: `action` matches `^[a-z_][a-z0-9_]*\.[a-z0-9_]+$` (≤64 characters). `entity_id` is optional: one id or a comma-separated list of at most 4, each matching `^[a-z_][a-z0-9_]*\.[a-z0-9_]+$`, ≤128 characters in total. `data` is optional, at most 4 pairs, keys `^[a-z0-9_]{1,32}$`, values strings, numbers or booleans (sent as strings; `true`/`false` lowercase), each ≤64 characters after conversion. No `$(…)` substitution: the panel runs it without the PC.
- At most 2 `homeassistant` steps per trigger and at most 24 in a page (layout budget).
- **Who runs it:** always the panel, with or without the PC. The host skips `homeassistant` steps (`run_action` returns at once and logs `run by the panel`). In a mixed list, PC steps run on the PC and HA steps on the panel, with no ordering between them; `review()` warns when an HA step follows a `delay`. If a trigger's list holds only HA steps, the host sends **no** `AD_FEEDBACK` for that press, and the panel gives the feedback.
- Firmware: `press_router` sends one `HomeassistantActionRequest` (35) per step: `service` = `action`, `data` = the pairs plus `entity_id`, `is_event=false`, `wants_response=false`. The flash is green when every step was written to a connection that has sent `SubscribeHomeassistantServicesRequest` (34). It is red when there is no such connection (Wi-Fi down, API off, HA not subscribed). HA gives no success reply without `wants_response`, and `wants_response` makes HA fail actions that do not return data, so green means "delivered", not "done". The editor says this.
- HA must have *Allow the device to perform Home Assistant actions* ticked in the ESPHome integration options (default off). The panel cannot detect it, so the dialog and the action editor say so.
- UI (`ui.cpp send_press`): a key with HA steps for this trigger gets the pending pulse when `deck_network_t.api_client` is true, and red at once otherwise. That replaces today's "no host means red" rule for such keys. The result comes back through `deck_model_request_feedback`, as host feedback does.

### C.2 Following an entity

Button option in the config:

```json
"ha_state": {"entity_id": "sensor.living_room_temperature", "attribute": "", "show": "value", "on": ["on"], "unit": "°C"}
```

- `show`: `accent` (the key's color when the state is in `on`, otherwise the dim gray `#5A6270`), `value` (the state text, plus `unit`, as the key's `sub` line, or as the label on a 1-slot key with the title hidden), or `both`.
- Checks: `entity_id` as above (one id only), `attribute` `^[a-z0-9_]{0,32}$`, `on` at most 4 strings of ≤16 characters (default `["on"]`), `unit` ≤6 characters, at most 18 followed keys per page and at most 18 distinct entity/attribute pairs.
- Firmware: after HA sends `SubscribeHomeAssistantStatesRequest` (38), the panel sends one `SubscribeHomeAssistantStateResponse` (39) per distinct entity/attribute pair on the current layout. It sends them again on every reconnect and after every layout change. Each `HomeAssistantStateResponse` (40) goes to `deck_model_set_ha_state(button_id, text)`, which updates color, label or `sub` in place and bumps `live_version`, so the key is never rebuilt under a finger. Without a state (just booted, HA away), the host's label and color show as they do today. A state older than an HA disconnect is kept but drawn at 60 % opacity.

### C.3 How the layout carries it

The key entry gains two optional fields, sent only when the panel reports `"ha":1` (otherwise the host strips them and the editor shows *update the panel firmware*):

```json
{"id":3,"label":"Kitchen","ha":{"p":[{"a":"light.toggle","e":"light.kitchen","d":{"brightness_pct":"50"}}],"h":[…],"d":[…]},
 "hs":{"e":"light.kitchen","a":"","m":"a","on":["on"],"u":""}}
```

- `p`/`h`/`d` are the HA steps for press, hold and double; `m` is `a` (accent), `v` (value) or `b` (both). `hold`/`double` are already set by the host when those lists are non-empty, so the panel reports holds and marks doubles.
- Firmware storage: `deck_button_t` stays small. A separate table in `deck_model` holds at most 24 steps and 18 follow specs, filled by `deck_model_ha_from_json(const char *layout_json)`, called right after `deck_model_buttons_from_json` on both the USB push and `layout_load`. So the saved offline layout carries the HA keys, and they work after a reboot without the PC. Accessors: `int deck_model_ha_steps(int button_id, char trigger, deck_ha_step_t *out, int max)`, `int deck_model_ha_follows(deck_ha_follow_t *out, int max)`, and `uint32_t deck_model_ha_version(void)`.
- An invalid `ha` or `hs` makes the layout `INVALID`, the same rule as other key fields. Older firmware ignores unknown fields. The 8,192-byte limit still applies, and `layout_bytes` is checked by the host before sending.

### C.4 Editor

- Action picker: *Home Assistant* with fields Action (text with a datalist: `light.toggle`, `switch.toggle`, `scene.turn_on`, `script.turn_on`, `media_player.media_play_pause`, `cover.toggle`, `input_boolean.toggle`), Entity, and up to 4 data rows. The help text says it runs on the panel even with the PC off, and that HA must allow device actions. No HA token or REST call from the PC: entity ids are typed by hand in v1.
- Style tab: *Follow a Home Assistant entity* with entity, attribute, show (*Color* / *Value* / *Both*), on-states and unit.
- `action_preview.py` describes the action as `Home Assistant: light.toggle on light.kitchen`.
- `review()` findings: HA keys while `panel.homeassistant.enabled` is false; HA keys on a panel without `"ha":1`; HA step after a delay.

### C.5 Stage C tests

- Native: `deck_model_ha_from_json` (valid, each invalid field, limits, restore from file), message 35 encoding with data pairs, the 39 subscription list (deduplicated, re-sent on reconnect and after a layout change), a 40 state updating label and color in place (render frames for accent/value/both), feedback green/red rules.
- Host: `_check_homeassistant` and `ha_state` checks, layout entries with `ha`/`hs` only for `"ha":1` panels, host skips HA steps, no `AD_FEEDBACK` for HA-only presses, preview text.
- PC test script `--stage c`: with a test `input_boolean.tessera_test` in HA, the user presses a key with `input_boolean.toggle`, and the script (as a second aioesphomeapi client, or reading HA's state) sees the toggle. A key following that entity changes color within 1 s. The test is repeated with the USB cable unplugged and the panel on a USB power supply.

---

## Security

- **Off by default.** No credentials means the hosted stack is never started. The API is a separate opt-in and runs only on station Wi-Fi. There is no access point mode, captive portal, Web server, OTA over Wi-Fi, or log streaming over Wi-Fi.
- **Provisioning only over USB.** USB is already fully trusted (it can flash firmware), so `AD_WIFI_SET` and `AD_API_KEY` add no new trust.
- **Encryption required.** The server speaks Noise only and rejects plaintext. Key: 32 random bytes made on the panel, rotated with `AD_API_KEY NEW`.
- **What a LAN attacker without the key gets:** the mDNS TXT records (device name, friendly name, MAC, version, project), the server hello (name and MAC), and the ability to open at most 2 TCP connections that close after 10 s without a valid handshake. That allows a denial of service against HA's connection, nothing more: the slot rules above keep an established HA session, but a flood on 6053 can keep HA from reconnecting until it ends. lwIP gives up on half-open connections sooner (`CONFIG_LWIP_TCP_SYNMAXRTX=4`, `CONFIG_LWIP_TCP_MAXRTX=8`), and unused mDNS parts are off. Still to measure on hardware: LVGL frame rate during a SYN flood. Malformed frames close the connection and are bounded (128-byte handshake, 1,024-byte messages); the parsers are fuzzed natively.
- **What someone with the key (or a compromised HA) gets:** key events, profile and page names, the backlight, the clock screen, and whether the PC is connected. They can switch profile or page on the PC when it is connected. They **cannot** press keys, run PC actions, type, read the layout's PC actions, read the Wi-Fi password, or change Wi-Fi, the key or the firmware: no API message maps to those. In stage C, the HA actions the panel calls are defined only by the layout pushed over USB.
- **Credentials and keys stay out of logs and diagnostics:** the panel never logs or echoes the password or the PSK. `get_info` and the status lines carry neither. On the PC, the password exists only in memory between the dialog and the serial write (control API on 127.0.0.1, owner token, not via a file or the job queue). The PSK is shown on request and never stored. Diagnostics redact the SSID, IP and MAC. Canary tests enforce this.
- **At rest on the panel (accepted risk):** NVS is not encrypted (flash encryption is not enabled in Tessera), so someone holding the board can read the password and the PSK from flash, and after `AD_API_KEY NEW` the old key can stay readable in erased NVS pages until they are reused. They could equally use USB, which can already flash any firmware. Tessera makes no claim of confidentiality at rest; the fix, if ever needed, is flash encryption (release mode) on shipped units. Documented in USING.md, with the advice to put the panel on an IoT VLAN.
- **HA side:** device-initiated actions need the user's explicit opt-in in HA.

## Risks and open items

See the list returned with this design. The main ones: the hosted/C6 version match, hosted init behavior with a missing C6, internal DMA RAM under LVGL, PSA crypto Kconfig on IDF 6.1, mDNS through the C6 bridge, flash slot size, and HA behavior for `wants_response` and the time zone field.

## Exact interfaces for stage A builders

1. `main/wifi_config.h/.c`: `WIFI_SSID_MAX 32`, `WIFI_PASSWORD_MAX 64`, `wifi_credentials_t {ssid[33], password[65]}`, `bool wifi_config_from_json(const char *json, wifi_credentials_t *out, const char **field)` (field ∈ `json|ssid|password`), `void wifi_credentials_wipe(wifi_credentials_t *)`. Pure C plus cJSON; compiled into `tests/native`.
2. `main/wifi_service.h/.c`: the `wifi_svc_state_t` values off 0 / connecting 1 / connected 2 / failed 3; `wifi_svc_reason_t` none, no_coprocessor, init, no_ap, auth, no_ip, lost, crashed, storage; `wifi_svc_status_t`; `wifi_service_init`, `wifi_service_set`, `wifi_service_clear`, `wifi_service_status`, `wifi_service_version`, `wifi_service_state_name`, `wifi_service_reason_name`, `wifi_service_connected`. NVS namespace `tessera_net` with keys `ssid`, `pass` and `boot_guard`. Wi-Fi storage RAM. Task `tessera_wifi` on core 1, priority 2, 4 KB. No hosted call without stored credentials. No `ESP_ERROR_CHECK` on Wi-Fi calls. Never logs the password.
3. `main/deck_model.h`: `deck_network_t`, `deck_model_set_network`, `deck_model_network` and `deck_model_network_version`.
4. `main/protocol_version.h`: `TESSERA_PROTOCOL 5`. `main.cpp`: `AD_WIFI_SET <json>` gives `AD_WIFI_SET OK` | `INVALID json|ssid|password` | `FAILED storage`; `AD_WIFI_CLEAR` gives `AD_WIFI_CLEAR OK` | `FAILED storage`; `AD_WIFI_STATUS` gives one `{"type":"wifi","state":…,"reason"?,"ssid"?,"ip"?,"rssi"?,"mac"?,"cp"?}` line; the same line is sent unsolicited on a `wifi_service_version()` change, at most once a second; `get_info` gets `"wifi":"<state>"`; the line buffer is zeroed after `AD_WIFI_SET`.
5. `ui.cpp`: an About sheet line with the texts in A.4, the card 336 px high.
6. `host/panel_serial.py`: `SUPPORTED_PROTOCOLS = (1, 2, 3, 4, 5)`, `WIFI_PROTOCOL = 5`, `WIFI_STATES`, `WIFI_REASONS`, `check_wifi_credentials`, `wifi_line`, `parse_wifi_status`, `PanelSerial.supports_wifi/wifi_set/wifi_clear/wifi_status`, and `wifi_done`/`wifi_reply`.
7. `host/tesserad.py`: `reader_loop` routing, `self.wifi`, `runtime['wifi']`, and `AD_WIFI_STATUS` after the handshake.
8. `host/control_api.py`: route `wifi` (owner only), with bodies and codes as in A.5.
9. `host/tessera_app.py`: command `panel-wifi`, which posts to `/v1/wifi` and never writes the password to a file.
10. `host/config_check.py`: `panel.wifi = {"ssid": 1-32 UTF-8 bytes}`, and no other keys.
11. `host/diagnostics.py`: redact the SSID, IP and MAC.
12. `host/editor`: `#wifi-dialog`, with `openWifi`, `refreshWifi`, `sendWifi` and `forgetWifi`, gated on `device.connected && device.protocol >= 5`.
13. Tests: native `wifi_config`/network model/About render; `tests/test_wifi.py` (protocol gating, bytes, replies, status parsing, canary leak tests, control API scopes, config checks); the editor smoke test; and `tests/hardware_smoke.py --wifi` with `getpass`.
