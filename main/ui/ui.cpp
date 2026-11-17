// Tessera cockpit UI: a rail of four screens (keys, agents, mixer, status) beside the content.
#include "ui.h"
#include "icon_pack.h"
#include "deck_images.h"
#include "deck_model.h"
#include "time_service.h"
#include "ui_palette.h"
#include <Arduino.h>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <lvgl.h>
#include "src/misc/cache/instance/lv_image_cache.h"

extern const lv_font_t fq_font_dejavu_16;
extern const lv_font_t fq_font_dejavu_20;
extern const lv_font_t fq_font_dejavu_24;
extern const lv_font_t fq_font_dejavu_28;
extern const lv_font_t fq_font_dejavu_bold_20;
extern const lv_font_t fq_font_dejavu_bold_24;
extern const lv_font_t fq_font_dejavu_bold_28;
extern const lv_font_t fq_font_dejavu_bold_40;

namespace {
/* Drawn for 1024 x 600. ui_init reads the screen's size and scales every length by sc(), so a 7" 800 x 480 screen
 * gets the same layout at about the same physical size, with text one size down (fit). */
int W=1024,H=600,Rail=84,Pad=26,Top=22,ContentW=W-Rail-2*Pad,HeadH=50,RailTop=84,RailPitch=60;
float scale=1;bool small=false;
int sc(int v) {return static_cast<int>(std::lround(v*scale));}
const lv_font_t *fit(const lv_font_t *font) {
    if(!small)return font;
    if(font==&fq_font_dejavu_20)return &fq_font_dejavu_16;
    if(font==&fq_font_dejavu_24)return &fq_font_dejavu_20;
    if(font==&fq_font_dejavu_28)return &fq_font_dejavu_24;
    if(font==&fq_font_dejavu_bold_24)return &fq_font_dejavu_bold_20;
    if(font==&fq_font_dejavu_bold_28)return &fq_font_dejavu_bold_24;
    if(font==&fq_font_dejavu_bold_40)return &fq_font_dejavu_bold_28;
    return font;  /* 16 and bold 20 are the smallest DejaVu sizes */
}
/* From a label's top to its baseline. */
int ascent(lv_obj_t *shown) {const auto *font=lv_obj_get_style_text_font(shown,LV_PART_MAIN);return lv_font_get_line_height(font)-font->base_line;}
using namespace ui_palette;
uint32_t mix(uint32_t from,uint32_t to,float t);
/* A key marked "confirm" sends its press only after this long a hold; the lock badge unlocks after LockHoldMs. */
constexpr uint32_t ConfirmMs=600,LockHoldMs=2000;
char firmware_version[32]="unknown";
/* The host pings every second; three missed pings mean nobody runs the keys. */
constexpr int64_t HostTimeoutMs=3500;
/* A pressed key stays highlighted until the host confirms it. Long multi-step
 * actions confirm late, so the highlight only gives up after this long. */
constexpr uint32_t PendingMs=10000;

enum View {ViewKeys=0,ViewAgents,ViewMixer,ViewStatus,ViewCount};
const char *const ViewIcons[ViewCount]={"lc:e0ff","lc:e1bb","lc:e162","lc:e038"};
const char *const ViewNames[ViewCount]={"keys","agents","mixer","status"};
lv_obj_t *screen=nullptr,*views[ViewCount]{},*rail_items=nullptr,*rail_btn[DECK_RAIL_MAX]{},*rail_gl[DECK_RAIL_MAX]{};
deck_rail_item_t rail_list[DECK_RAIL_MAX]{};
int rail_count=0,rail_agents=-1;uint32_t rail_version=0;
void refresh_rail();
void build_rail();
lv_obj_t *rail_marker=nullptr,*rail_dot=nullptr,*clock_label=nullptr,*link_label=nullptr;
int view=ViewKeys;
/* Model state that several widgets show. update() sets these on the LVGL task and bound widgets follow; a widget's
 * bindings go away with it when it is deleted. */
lv_subject_t *link_subject=nullptr;        /* 1 while the PC answers pings, else 0; -1 until update_link has looked */
lv_subject_t *lock_subject=nullptr;        /* 1 while the panel is locked */
lv_subject_t *brightness_subject=nullptr;  /* the About sheet's slider and its percentage */

/* Keys: indexed by slot (id - 1), six to a row. */
lv_obj_t *keys_area=nullptr,*page_label=nullptr,*profile_label=nullptr;
lv_obj_t *keys[DECK_MAX_BUTTONS]{},*name_label[DECK_MAX_BUTTONS]{},*glyph_label[DECK_MAX_BUTTONS]{},*value_label[DECK_MAX_BUTTONS]{};
lv_obj_t *sub_label[DECK_MAX_BUTTONS]{},*bar_fill[DECK_MAX_BUTTONS]{},*ring_arc[DECK_MAX_BUTTONS]{};
bool gauge[DECK_MAX_BUTTONS]{};  /* ring_arc shows gauge_percent, not progress */
int bar_width[DECK_MAX_BUTTONS]{};
int ids[DECK_MAX_BUTTONS]{};
uint32_t flash_until[DECK_MAX_BUTTONS]{},base_bg[DECK_MAX_BUTTONS]{};
/* By button id: a press waits for its answer; a new layout makes that answer stale, since the id then names
 * another key (a folder key's feedback arrives after the page it opened). Feedback nobody pressed for still shows. */
bool awaiting[DECK_MAX_BUTTONS+1]{},stale[DECK_MAX_BUTTONS+1]{};
uint32_t button_version=0,live_version=0,context_version=0;
struct ImageTile {
    std::shared_ptr<const DeckImage> image;
    lv_obj_t *widget=nullptr;
    lv_image_dsc_t descriptor{};
    uint32_t due=0;
    size_t frame=0;
};
ImageTile images[DECK_MAX_BUTTONS];

lv_obj_t *agents_area=nullptr,*agents_summary=nullptr;
uint32_t agents_version=0,agents_dot=0;bool agents_dirty=false;  /* a hidden agents screen is rebuilt when shown */

int FaderW=163,FaderGap=18,TrackH=340,TrackW=110;  /* set by ui_init */
lv_obj_t *mixer_area=nullptr,*fader_zone[DECK_FADERS_MAX]{},*fader_fill[DECK_FADERS_MAX]{},*fader_knob[DECK_FADERS_MAX]{};
lv_obj_t *fader_value[DECK_FADERS_MAX]{},*fader_mute[DECK_FADERS_MAX]{},*fader_icon[DECK_FADERS_MAX]{};
deck_fader_t faders[DECK_FADERS_MAX]{};
int fader_count=0;
uint32_t fader_hold[DECK_FADERS_MAX]{},fader_sent[DECK_FADERS_MAX]{},faders_version=0;

int StatW=211,StatH=156,StatGap=14;  /* set by ui_init */
lv_obj_t *stats_area=nullptr,*stats_summary=nullptr,*stat_card[DECK_STATS_MAX]{},*stat_value[DECK_STATS_MAX]{};
lv_obj_t *stat_unit[DECK_STATS_MAX]{},*stat_fill[DECK_STATS_MAX]{},*stat_name[DECK_STATS_MAX]{};
int stat_count=-1;
uint32_t stats_version=0;

/* Shared styles: LVGL keeps one copy for all objects instead of the same local properties on each one.
 * An added style still wins over the theme; a local property (a key's own color) wins over both. */
lv_style_t flat_style,key_down_style;
void init_styles() {
    lv_style_init(&flat_style);lv_style_set_bg_opa(&flat_style,LV_OPA_COVER);lv_style_set_border_width(&flat_style,0);
    lv_style_set_pad_all(&flat_style,0);lv_style_set_shadow_width(&flat_style,0);
    /* A key under the finger: it darkens and sinks. */
    lv_style_init(&key_down_style);lv_style_set_bg_color(&key_down_style,lv_color_hex(PressedBg));
    lv_style_set_transform_width(&key_down_style,sc(-4));lv_style_set_transform_height(&key_down_style,sc(-4));
}
void flat(lv_obj_t *object,uint32_t color) {
    lv_obj_add_style(object,&flat_style,0);lv_obj_set_style_bg_color(object,lv_color_hex(color),0);
    lv_obj_set_scrollable(object,false);
}
lv_obj_t *label(lv_obj_t *parent,const char *value,int x,int y,int width,const lv_font_t *font,uint32_t color) {
    auto *result=lv_label_create(parent);lv_obj_set_pos(result,x,y);lv_obj_set_width(result,width);
    lv_label_set_text(result,value);lv_label_set_long_mode(result,LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_font(result,font,0);lv_obj_set_style_text_color(result,lv_color_hex(color),0);
    lv_obj_set_height(result,lv_font_get_line_height(font));  /* one line that ends in dots, never a second line */
    return result;
}
/* A plain surface that touches pass through. */
lv_obj_t *box(lv_obj_t *parent,int x,int y,int w,int h,int radius,uint32_t color) {
    auto *item=lv_obj_create(parent);flat(item,color);lv_obj_set_pos(item,x,y);lv_obj_set_size(item,w,h);
    lv_obj_set_style_radius(item,radius,0);lv_obj_set_clickable(item,false);
    return item;
}
lv_obj_t *clear_box(lv_obj_t *parent,int x,int y,int w,int h) {
    auto *item=box(parent,x,y,w,h,0,Bg);lv_obj_set_style_bg_opa(item,LV_OPA_TRANSP,0);
    return item;
}
/* A Lucide icon centred on (cx, cy) and drawn `px` high; the font has one size (60), smaller ones are scaled. */
lv_obj_t *glyph(lv_obj_t *parent,const char *name,int cx,int cy,int px,uint32_t color) {
    char packed[5]{};
    if(!deck_lucide_glyph(name,packed))return nullptr;
    const int line=deck_lucide_60.line_height;
    auto *item=label(parent,packed,cx-30,cy-line/2,60,&deck_lucide_60,color);
    lv_obj_set_style_text_align(item,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_clickable(item,false);
    if(px!=60){
        lv_obj_set_style_transform_pivot_x(item,30,0);lv_obj_set_style_transform_pivot_y(item,line/2,0);
        lv_obj_set_style_transform_scale(item,px*256/60,0);
    }
    return item;
}
/* A full circle that fills clockwise from the top for 0..100, with no knob and no touch of its own. */
lv_obj_t *make_ring(lv_obj_t *parent,int size,int width,uint32_t track,uint32_t fill,int value) {
    auto *arc=lv_arc_create(parent);lv_obj_set_size(arc,size,size);
    lv_arc_set_rotation(arc,270);lv_arc_set_bg_angles(arc,0,360);lv_arc_set_range(arc,0,100);lv_arc_set_value(arc,value);
    lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
    lv_obj_set_style_arc_width(arc,width,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,width,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc,lv_color_hex(track),LV_PART_MAIN);lv_obj_set_style_arc_color(arc,lv_color_hex(fill),LV_PART_INDICATOR);
    return arc;
}
const char *fallback_icon(const char *name) {
    struct Entry{const char *name,*symbol;};
    static const Entry values[]={
      {"ok",LV_SYMBOL_OK},{"close",LV_SYMBOL_CLOSE},{"settings",LV_SYMBOL_SETTINGS},
      {"home",LV_SYMBOL_HOME},{"folder",LV_SYMBOL_DIRECTORY},{"download",LV_SYMBOL_DOWNLOAD},
      {"refresh",LV_SYMBOL_REFRESH},{"play",LV_SYMBOL_PLAY},{"pause",LV_SYMBOL_PAUSE},
      {"stop",LV_SYMBOL_STOP},{"plus",LV_SYMBOL_PLUS},{"minus",LV_SYMBOL_MINUS},
      {"loop",LV_SYMBOL_LOOP},{"list",LV_SYMBOL_LIST},{"upload",LV_SYMBOL_UPLOAD},
      {"bolt",LV_SYMBOL_CHARGE},{"bell",LV_SYMBOL_BELL},{"wifi",LV_SYMBOL_WIFI},
      {"trash",LV_SYMBOL_TRASH},{"edit",LV_SYMBOL_EDIT}};
    for(const auto& item:values)if(!strcmp(name,item.name))return item.symbol;
    return LV_SYMBOL_OK;
}
int slot_of(lv_event_t *event) {return static_cast<int>(reinterpret_cast<intptr_t>(lv_event_get_user_data(event)));}
void *slot_data(int slot) {return reinterpret_cast<void*>(static_cast<intptr_t>(slot));}

/* Set a color only when it differs: LVGL redraws the object on every set, even to the same value. */
void set_color(lv_obj_t *object,lv_style_prop_t prop,uint32_t hex,lv_style_selector_t selector=0) {
    const lv_color_t color=lv_color_hex(hex);lv_style_value_t value{};
    if(lv_obj_get_local_style_prop(object,prop,&value,selector)==LV_STYLE_RES_FOUND&&lv_color_eq(value.color,color))return;
    value.color=color;lv_obj_set_local_style_prop(object,prop,value,selector);
}

/* ---- Keys ---------------------------------------------------------------------------------------- */
void image_frame(ImageTile& value) {
    value.descriptor.header.magic=LV_IMAGE_HEADER_MAGIC;value.descriptor.header.cf=LV_COLOR_FORMAT_ARGB8888;
    value.descriptor.header.w=value.image->width;value.descriptor.header.h=value.image->height;
    value.descriptor.header.stride=value.image->width*4;value.descriptor.data=value.image->frames[value.frame].data();
    value.descriptor.data_size=value.image->frames[value.frame].size();lv_image_cache_drop(&value.descriptor);
    lv_image_set_src(value.widget,&value.descriptor);lv_obj_invalidate(value.widget);
    value.due=millis()+value.image->durations[value.frame];
}
void pulse_opa(void *object,int32_t value) {lv_obj_set_style_bg_opa(static_cast<lv_obj_t*>(object),static_cast<lv_opa_t>(value),0);}
void flash(int slot,uint32_t color,uint32_t ms) {
    auto *tile=keys[slot];lv_anim_delete(tile,pulse_opa);lv_obj_set_style_bg_opa(tile,LV_OPA_COVER,0);
    lv_obj_set_style_bg_color(tile,lv_color_hex(color),0);flash_until[slot]=millis()+ms;
    if(color!=PressedBg)return;
    /* Waiting for the PC: a slow pulse says the press arrived and the action is running. */
    lv_anim_t pulse;lv_anim_init(&pulse);lv_anim_set_var(&pulse,tile);lv_anim_set_exec_cb(&pulse,pulse_opa);
    lv_anim_set_values(&pulse,LV_OPA_COVER,LV_OPA_50);lv_anim_set_duration(&pulse,450);lv_anim_set_reverse_duration(&pulse,450);
    lv_anim_set_repeat_count(&pulse,LV_ANIM_REPEAT_INFINITE);lv_anim_start(&pulse);
}
void send_press(int slot,bool hold) {
    /* Refused when a new layout arrived since this grid was built: the key at this slot may belong to it. */
    if(!deck_model_record_touch(ids[slot],hold,button_version))return;
    awaiting[ids[slot]]=true;stale[ids[slot]]=false;
    /* Without a host nothing runs the action: say so at once instead of
     * flashing as if it worked. */
    if(deck_model_host_linked(HostTimeoutMs))flash(slot,PressedBg,PendingMs);
    else flash(slot,AlertBg,500);
}
void press(lv_event_t *event) {
    const int slot=slot_of(event);
    if(slot<0||slot>=DECK_MAX_BUTTONS||!ids[slot]||deck_model_locked())return;
    send_press(slot,lv_event_get_code(event)==LV_EVENT_LONG_PRESSED);
}
/* A confirm key: a ring fills over ConfirmMs while the finger stays, and only then is the press sent
 * (by update()); lifting the finger or sliding off early sends nothing. */
lv_obj_t *confirm_ring=nullptr;int confirm_slot=-1;uint32_t confirm_started=0;
void confirm_fill(void *arc,int32_t value) {lv_arc_set_value(static_cast<lv_obj_t*>(arc),value);}
void confirm_stop() {if(confirm_ring)lv_obj_delete(confirm_ring);confirm_ring=nullptr;confirm_slot=-1;}  /* the delete ends its anim */
void confirm_touch(lv_event_t *event) {
    const int slot=slot_of(event);
    if(slot<0||slot>=DECK_MAX_BUTTONS||!ids[slot])return;
    confirm_stop();
    if(lv_event_get_code(event)!=LV_EVENT_PRESSED||deck_model_locked())return;
    auto *tile=keys[slot];const int size=LV_MIN(lv_obj_get_width(tile),lv_obj_get_height(tile))-sc(28);
    auto *arc=confirm_ring=make_ring(tile,size,sc(8),Bg,Accent,0);lv_obj_center(arc);
    confirm_slot=slot;confirm_started=millis();
    lv_anim_t fill;lv_anim_init(&fill);lv_anim_set_var(&fill,arc);lv_anim_set_exec_cb(&fill,confirm_fill);
    lv_anim_set_values(&fill,0,100);lv_anim_set_duration(&fill,ConfirmMs);lv_anim_start(&fill);
}
void confirm_tick() {
    if(confirm_slot<0)return;
    if(deck_model_locked()){confirm_stop();return;}
    if(millis()-confirm_started<ConfirmMs)return;
    const int slot=confirm_slot;confirm_stop();send_press(slot,false);
}
/* There is no next or previous page: a swipe right is Back, the line the Keys button sends while the keys
 * show. A swipe is never a tap on the key it started on. */
void swipe(lv_event_t *) {
    auto *indev=lv_indev_active();if(!indev)return;
    const lv_dir_t dir=lv_indev_get_gesture_dir(indev);
    if(dir!=LV_DIR_LEFT&&dir!=LV_DIR_RIGHT)return;
    confirm_stop();lv_indev_wait_release(indev);
    if(dir!=LV_DIR_RIGHT||deck_model_locked()||!deck_model_host_linked(HostTimeoutMs))return;
    for(int i=0;i<rail_count;++i)if(rail_list[i].kind==ViewKeys){
        char line[40];snprintf(line,sizeof(line),"{\"type\":\"rail\",\"i\":%d}",i);deck_model_queue_line(line);return;}
}
/* A touch on a dimmed panel only wakes it, wherever it lands, and never
 * reaches a key: the indev ignores the rest of the touch until release. */
void wake_touch(lv_event_t *event) {
    if(!deck_model_dimmed())return;
    deck_model_request_wake();
    auto *indev=static_cast<lv_indev_t*>(lv_event_get_target(event));
    lv_indev_stop_processing(indev);lv_indev_wait_release(indev);
}
/* The deck: six by three keys, each in the slot its id names, so the panel shows what the editor shows. */
uint32_t image_generation=0;bool image_missing=false;  /* a key waits for an image the host has not sent yet */
struct ImageWait {char icon[DECK_ICON_NAME_MAX+1];int cx,cy;} image_wait[DECK_MAX_BUTTONS]{};  /* where it goes */
char asked_images[DECK_MAX_BUTTONS][64]{};uint32_t asked_layout=0,asked_at=0;
bool ask_once(const char *icon) {  /* each rebuild while images stream in would ask again and crowd out touches */
    if(asked_layout!=deck_model_buttons_version()||millis()-asked_at>60000){memset(asked_images,0,sizeof(asked_images));asked_layout=deck_model_buttons_version();asked_at=millis();}
    for(auto& asked:asked_images){if(!strncmp(asked,icon,sizeof(asked_images[0])-1))return false;if(!asked[0]){snprintf(asked,sizeof(asked_images[0]),"%s",icon);return true;}}
    return false;
}
/* The editor's Text size and Bold. There is no bold 16 px font, so bold at 16 uses bold 20. */
const lv_font_t *title_font(const deck_button_t& value) {
    switch(value.title_size) {
      case 20:return fit(value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_20);
      case 24:return fit(value.title_bold?&fq_font_dejavu_bold_24:&fq_font_dejavu_24);
      case 28:return fit(value.title_bold?&fq_font_dejavu_bold_28:&fq_font_dejavu_28);
      default:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_16;
    }
}
/* The ring's inside is about 88 px wide: longer values ("3.8GHz", "302rpm") step down a size instead of spilling over. */
const lv_font_t *gauge_font(const char *text) {
    size_t n=strlen(text);
    if(small)return n<=4?&fq_font_dejavu_bold_20:&fq_font_dejavu_16;  /* a 69 px inside */
    return n<=4?&fq_font_dejavu_bold_28:n==5?&fq_font_dejavu_bold_24:&fq_font_dejavu_bold_20;
}
/* Sets a ring's value and its size, keeping the line centred where it was. */
void gauge_value(lv_obj_t *shown,const char *text) {
    const lv_font_t *font=gauge_font(text);int line=lv_font_get_line_height(font);
    int mid=lv_obj_get_style_y(shown,LV_PART_MAIN)+lv_obj_get_style_height(shown,LV_PART_MAIN)/2;
    lv_label_set_text(shown,text);lv_obj_set_style_text_font(shown,font,0);
    lv_obj_set_height(shown,line);lv_obj_set_y(shown,mid-line/2);
}
void build_keys() {
    /* Versions read before the copy: a change that lands during it bumps them again and is drawn next tick. */
    const uint32_t buttons_now=deck_model_buttons_version(),live_now=deck_model_live_version();
    if(button_version!=buttons_now)for(int id=0;id<=DECK_MAX_BUTTONS;++id)if(awaiting[id]){stale[id]=true;awaiting[id]=false;}
    image_missing=false;image_generation=deck_image_generation();
    memset(name_label,0,sizeof(name_label));memset(glyph_label,0,sizeof(glyph_label));memset(value_label,0,sizeof(value_label));
    memset(sub_label,0,sizeof(sub_label));memset(bar_fill,0,sizeof(bar_fill));memset(ring_arc,0,sizeof(ring_arc));memset(gauge,0,sizeof(gauge));
    memset(image_wait,0,sizeof(image_wait));
    confirm_ring=nullptr;confirm_slot=-1;  /* the clean below deletes a ring in progress */
    lv_obj_clean(keys_area);for(auto& image:images){lv_image_cache_drop(&image.descriptor);image=ImageTile{};}
    memset(keys,0,sizeof(keys));memset(ids,0,sizeof(ids));memset(flash_until,0,sizeof(flash_until));
    const int Gap=sc(12),KeyW=(ContentW-5*Gap)/6,KeyH=(H-2*Top-HeadH-2*Gap)/3;  /* 138 x 160 on 1024 x 600 */
    const int count=deck_model_button_count();
    bool covered[DECK_MAX_BUTTONS]{};
    for(int n=0;n<count;++n){deck_button_t wide{};
        if(deck_model_get_button(n,&wide)&&wide.id>=1&&wide.id<=DECK_MAX_BUTTONS)
            for(int extra=1;extra<wide.span&&wide.id-1+extra<DECK_MAX_BUTTONS&&(wide.id-1)%6+extra<6;++extra)covered[wide.id-1+extra]=true;}
    for(int n=0;n<count;++n) {
        deck_button_t value{};
        if(!deck_model_get_button(n,&value)||value.id<1||value.id>DECK_MAX_BUTTONS)continue;
        const int slot=value.id-1;
        const int cells=value.span<2?1:(value.span>6-slot%6?6-slot%6:value.span);
        auto *tile=lv_button_create(keys_area);keys[slot]=tile;ids[slot]=value.id;
        const int width=cells*KeyW+(cells-1)*Gap;
        lv_obj_set_pos(tile,(slot%6)*(KeyW+Gap),(slot/6)*(KeyH+Gap));lv_obj_set_size(tile,width,KeyH);
        base_bg[slot]=(value.style&DECK_STYLE_BG)?value.bg:Card;
        flat(tile,base_bg[slot]);lv_obj_set_style_radius(tile,sc(20),0);
        if(value.style&DECK_STYLE_BORDER){lv_obj_set_style_border_width(tile,2,0);lv_obj_set_style_border_color(tile,lv_color_hex(value.border),0);}
        lv_obj_add_style(tile,&key_down_style,LV_STATE_PRESSED);
        const bool title_top=cells==1&&value.title_position==1;  /* the icon moves down to make room for the title */
        const int cx=cells>1?sc(58):KeyW/2,cy=cells>1?KeyH/2-sc(12):title_top?KeyH-sc(60):sc(60);
        auto image=deck_image_get(value.icon);
        if(!image&&!strncmp(value.icon,"im:",3)){
            image_missing=true;
            /* The host may believe the panel still has it (the cache dropped it): ask for it again. */
            if(ask_once(value.icon)){char line[96];snprintf(line,sizeof(line),"{\"type\":\"image\",\"id\":\"%.60s\"}",value.icon);deck_model_queue_line(line);}
        }
        if(cells>1&&value.ring&&value.has_progress){
            /* A ring (a timer) on the left, the time big to its right. */
            const int ring=sc(104);
            ring_arc[slot]=make_ring(tile,ring,sc(10),0x0A0E10,value.color,value.progress);lv_obj_set_pos(ring_arc[slot],sc(14),(KeyH-ring)/2);
        } else if(value.has_gauge){
            /* A ring filled to the percentage with the value inside; the badge says what is measured. */
            const int ring=sc(104);
            ring_arc[slot]=make_ring(tile,ring,sc(8),0x0A0E10,value.color,value.gauge_percent);lv_obj_set_pos(ring_arc[slot],cx-ring/2,cy-ring/2);
            gauge[slot]=true;
            auto *shown=value_label[slot]=label(tile,value.gauge_text,cx-KeyW/2,cy-18,KeyW,&fq_font_dejavu_bold_28,value.color);
            gauge_value(shown,value.gauge_text);
            lv_obj_set_style_text_align(shown,LV_TEXT_ALIGN_CENTER,0);
            if(value.gauge_badge[0])glyph(tile,value.gauge_badge,sc(18),sc(18),sc(20),Muted);
        } else if(image){
            auto& target=images[slot];target.image=image;target.widget=lv_image_create(tile);
            lv_obj_set_pos(target.widget,cx-image->width/2,cy-image->height/2);lv_obj_set_clickable(target.widget,false);
            image_frame(target);
        } else if(!(glyph_label[slot]=glyph(tile,value.icon,cx,cy,60,value.color))){
            auto *symbol=glyph_label[slot]=label(tile,fallback_icon(value.icon),0,cy-26,KeyW,&lv_font_montserrat_48,value.color);  /* icon size, not scaled */
            lv_obj_set_style_text_align(symbol,LV_TEXT_ALIGN_CENTER,0);
        }
        if(!image&&!ring_arc[slot]&&!strncmp(value.icon,"im:",3)){
            snprintf(image_wait[slot].icon,sizeof(image_wait[slot].icon),"%s",value.icon);image_wait[slot].cx=cx;image_wait[slot].cy=cy;}
        const uint32_t ink=(value.style&DECK_STYLE_TEXT)?value.text:Text;
        if(cells>1){
            /* Wide key: the title and a second line to the right of the icon, a progress bar underneath. */
            const int left=value.ring?sc(130):sc(112),room=width-left-sc(14);
            name_label[slot]=label(tile,value.label,left,value.ring?sc(40):sc(30),room,fit(value.ring?&fq_font_dejavu_bold_28:&fq_font_dejavu_bold_24),ink);
            sub_label[slot]=label(tile,value.sub,left,value.ring?sc(82):sc(70),room,fit(&fq_font_dejavu_20),Muted);
            if(value.has_progress&&!value.ring){
                bar_width[slot]=room;
                auto *track=box(tile,left,KeyH-sc(38),room,sc(6),3,Bg);
                bar_fill[slot]=box(track,0,0,room*value.progress/100,sc(6),3,value.color);
            }
        } else {
        /* Text size, position and bold from the editor: bottom (the default), top, middle or hidden. */
        const lv_font_t *font=title_font(value);const int px=lv_font_get_line_height(font);
        const int y=value.title_position==1?sc(10):value.title_position==2?(KeyH-px)/2:KeyH-px-sc(17);
        auto *name=name_label[slot]=label(tile,value.label,sc(4),y,KeyW-2*sc(4),font,ink);
        lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(name,value.title_position==3);
        }
        /* Small marks in the corner say what else a key does: a ring for a long press, two dots for a double tap. */
        int right=width-sc(12);
        if(value.has_double)for(int dot=0;dot<2;++dot){box(tile,right-sc(8),sc(12),sc(8),sc(8),sc(4),Muted);right-=sc(13);}
        if(value.has_hold){auto *ring=box(tile,right-sc(14),sc(9),sc(14),sc(14),sc(7),Card);lv_obj_set_style_bg_opa(ring,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(ring,2,0);lv_obj_set_style_border_color(ring,lv_color_hex(Muted),0);}
        if(value.confirm){for(auto code:{LV_EVENT_PRESSED,LV_EVENT_RELEASED,LV_EVENT_PRESS_LOST})lv_obj_add_event_cb(tile,confirm_touch,code,slot_data(slot));continue;}
        /* With a hold action, a click is a short press only; a long press reports a hold instead. */
        lv_obj_add_event_cb(tile,press,value.has_hold?LV_EVENT_SHORT_CLICKED:LV_EVENT_CLICKED,slot_data(slot));
        if(value.has_hold)lv_obj_add_event_cb(tile,press,LV_EVENT_LONG_PRESSED,slot_data(slot));
    }
    /* Empty slots stay visible as faint tiles, so the deck keeps its shape. */
    for(int slot=0;slot<DECK_MAX_BUTTONS;++slot)if(!keys[slot]&&!covered[slot])box(keys_area,(slot%6)*(KeyW+Gap),(slot/6)*(KeyH+Gap),KeyW,KeyH,sc(20),0x0D1316);
    button_version=buttons_now;live_version=live_now;
}
/* An image that arrives for a key on show goes into that key alone. A rebuild of the grid for it redrew every key,
 * once per image, and dropped a touch in progress. */
void fill_images() {
    image_generation=deck_image_generation();image_missing=false;
    for(int slot=0;slot<DECK_MAX_BUTTONS;++slot){
        auto& wait=image_wait[slot];if(!wait.icon[0]||!keys[slot])continue;
        auto image=deck_image_get(wait.icon);
        if(!image){image_missing=true;continue;}
        wait.icon[0]='\0';
        if(glyph_label[slot]){lv_obj_delete(glyph_label[slot]);glyph_label[slot]=nullptr;}
        auto& target=images[slot];target.image=image;target.widget=lv_image_create(keys[slot]);
        lv_obj_move_to_index(target.widget,0);  /* under the title and marks, where build_keys puts it */
        lv_obj_set_pos(target.widget,wait.cx-image->width/2,wait.cy-image->height/2);lv_obj_set_clickable(target.widget,false);
        image_frame(target);
    }
}
/* Labels, colors and gauge values change in place: a rebuild would drop a touch in progress. */
void update_live() {
    const uint32_t version=deck_model_live_version();  /* before the copy, as in build_keys */
    for(int n=0;n<deck_model_button_count();++n){deck_button_t item{};
        if(!deck_model_get_button(n,&item)||item.id<1||item.id>DECK_MAX_BUTTONS||!keys[item.id-1])continue;
        const int slot=item.id-1;
        if(value_label[slot]){
            if(strcmp(lv_label_get_text(value_label[slot]),item.gauge_text))gauge_value(value_label[slot],item.gauge_text);
            set_color(value_label[slot],LV_STYLE_TEXT_COLOR,item.color);
        }
        if(glyph_label[slot])set_color(glyph_label[slot],LV_STYLE_TEXT_COLOR,item.color);
        if(name_label[slot]&&strcmp(lv_label_get_text(name_label[slot]),item.label))lv_label_set_text(name_label[slot],item.label);
        if(sub_label[slot]&&strcmp(lv_label_get_text(sub_label[slot]),item.sub))lv_label_set_text(sub_label[slot],item.sub);
        /* Color is not structural (deck_model same_structure), so the gauges recolor here too. */
        if(bar_fill[slot]){lv_obj_set_width(bar_fill[slot],bar_width[slot]*item.progress/100);set_color(bar_fill[slot],LV_STYLE_BG_COLOR,item.color);}
        if(ring_arc[slot]){lv_arc_set_value(ring_arc[slot],gauge[slot]?item.gauge_percent:item.progress);set_color(ring_arc[slot],LV_STYLE_ARC_COLOR,item.color,LV_PART_INDICATOR);}}
    live_version=version;
}
/* ASCII only: UTF-8 multi-byte sequences are copied untouched. */
void title_case(const char *in,char *out,size_t size) {
    bool word_start=true;size_t n=0;
    for(;*in&&n+1<size;++in,++n) {
        const char c=*in;
        out[n]=word_start&&c>='a'&&c<='z'?static_cast<char>(c-32):c;
        word_start=c==' '||c=='-'||c=='_'||c=='/';
    }
    out[n]='\0';
}
void update_context() {
    const auto context=deck_model_context();
    char name[64],page[80],profile[64];
    title_case(context.page,name,sizeof(name));title_case(context.profile,profile,sizeof(profile));
    snprintf(page,sizeof(page),"%s%s",context.can_go_back?"<  ":"",name);
    lv_label_set_text(page_label,page);lv_label_set_text(profile_label,profile);context_version=deck_model_context_version();
    refresh_rail();
}

/* ---- Agents -------------------------------------------------------------------------------------- */
const char *const AgentActions[]={"allow","deny","stop","open"};
deck_agent_t lane_shown[DECK_AGENTS_MAX]{};  /* what each lane drew: a tap answers that agent, not whoever sits there now */
lv_obj_t *lane_state[DECK_AGENTS_MAX]{},*lane_text[DECK_AGENTS_MAX]{},*lane_sub[DECK_AGENTS_MAX]{};int lane_count=-1;
void set_text(lv_obj_t *shown,const char *text) {if(shown&&strcmp(lv_label_get_text(shown),text))lv_label_set_text(shown,text);}
void agent_state(const deck_agent_t& agent,char *out,size_t size) {
    snprintf(out,size,"%s%s%s",agent.state==DECK_AGENT_WAITING?"waiting for you":agent.state==DECK_AGENT_WORKING?"working":"idle",
             agent.at[0]&&agent.state!=DECK_AGENT_IDLE?" since ":"",agent.state!=DECK_AGENT_IDLE?agent.at:"");
}
const char *agent_words(const deck_agent_t& agent) {return agent.text[0]?agent.text:agent.state==DECK_AGENT_IDLE?"Ready":"Working";}
/* The same lanes with new words (a working agent's tool changes every few seconds): only those labels change.
 * A rebuild redrew most of the screen each time and dropped a tap on Open or Stop. */
bool update_agents(const deck_agent_t *list,int count) {
    if(agents_dirty||count!=lane_count)return false;
    for(int i=0;i<count;++i){const auto& was=lane_shown[i];const auto& now=list[i];
        if(strcmp(was.id,now.id)||strcmp(was.name,now.name)||was.state!=now.state||was.asks!=now.asks||!was.sub[0]!=!now.sub[0]
           ||(now.state==DECK_AGENT_WAITING&&strcmp(was.text,now.text)))return false;}  /* a question is laid out to fit */
    for(int i=0;i<count;++i){
        char state[40];agent_state(list[i],state,sizeof(state));set_text(lane_state[i],state);
        set_text(lane_text[i],agent_words(list[i]));set_text(lane_sub[i],list[i].sub);lane_shown[i]=list[i];
    }
    return true;
}
void agent_pressed(lv_event_t *event) {
    /* Locked: nobody may allow from the panel; the question still shows. No host: nobody would receive the answer. */
    if(deck_model_locked()||!deck_model_host_linked(HostTimeoutMs))return;
    const int packed=slot_of(event),index=packed>>4,action=packed&15;
    deck_agent_t list[DECK_AGENTS_MAX];const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    if(index<0||index>=DECK_AGENTS_MAX||action>3)return;
    const auto& shown=lane_shown[index];int at=0;
    while(at<count&&strcmp(list[at].id,shown.id))++at;
    if(at==count||list[at].state!=shown.state||list[at].asks!=shown.asks)return;  /* changed under the finger: the rebuild redraws it */
    char line[96];
    snprintf(line,sizeof(line),"{\"type\":\"agent\",\"id\":\"%s\",\"do\":\"%s\"}",shown.id,AgentActions[action]);
    deck_model_queue_line(line);
}
/* kind: 0 the answer we expect (filled), 1 neutral, 2 refusing */
void agent_button(lv_obj_t *lane,const char *text,int x,int kind,int index,int action) {
    auto *button=lv_button_create(lane);flat(button,kind==0?Accent:Card);
    lv_obj_set_pos(button,x,sc(25));lv_obj_set_size(button,sc(132),sc(96));lv_obj_set_style_radius(button,sc(18),0);
    if(kind){lv_obj_set_style_border_width(button,2,0);lv_obj_set_style_border_color(button,lv_color_hex(kind==2?0x7A3A42:Line),0);}
    lv_obj_set_style_bg_color(button,lv_color_hex(kind==0?0x3FB87C:RailOn),LV_STATE_PRESSED);
    auto *caption=lv_label_create(button);lv_label_set_text(caption,text);
    lv_obj_set_style_text_font(caption,&fq_font_dejavu_bold_20,0);
    lv_obj_set_style_text_color(caption,lv_color_hex(kind==0?0x06130C:kind==2?0xFF8A8A:Soft),0);lv_obj_center(caption);
    lv_obj_add_event_cb(button,agent_pressed,LV_EVENT_CLICKED,slot_data((index<<4)|action));
}
void update_rail_dot() {
    deck_agent_t list[DECK_AGENTS_MAX];bool waiting=false;
    const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    for(int i=0;i<count;++i)waiting=waiting||list[i].state==DECK_AGENT_WAITING;
    if(rail_dot)lv_obj_set_hidden(rail_dot,!waiting||view==ViewAgents||rail_agents<0);
}
/* Each tool's own icon (the same ones its keys use), so a lane is known at a glance. */
const char *agent_icon(const char *id) {
    return !strcmp(id,"claude")?"lc:e412":!strcmp(id,"codex")?"lc:e1bb":!strcmp(id,"zcode")?"lc:e3c6":"lc:e1bb";
}
void build_agents() {
    const uint32_t version=deck_model_agents_version();  /* before the copy, as in build_keys */
    deck_agent_t list[DECK_AGENTS_MAX];int waiting=0;
    const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    if(update_agents(list,count)){agents_version=agents_dot=version;return;}
    lv_obj_clean(agents_area);lane_count=count;
    memset(lane_state,0,sizeof(lane_state));memset(lane_text,0,sizeof(lane_text));memset(lane_sub,0,sizeof(lane_sub));
    for(int i=0;i<count;++i) {
        const auto& agent=lane_shown[i]=list[i];
        const uint32_t color=agent.state==DECK_AGENT_WAITING?Amber:agent.state==DECK_AGENT_WORKING?Cyan:Line;
        if(agent.state==DECK_AGENT_WAITING)++waiting;
        auto *lane=box(agents_area,0,i*sc(160),ContentW,sc(146),sc(20),Card);lv_obj_set_style_clip_corner(lane,true,0);
        box(lane,0,0,sc(7),sc(146),0,color);
        const bool asks=agent.state==DECK_AGENT_WAITING&&agent.asks;  /* only a real question gets Allow and Deny */
        const int buttons=asks||agent.state==DECK_AGENT_WORKING?2:1,text_w=ContentW-sc(26)-buttons*sc(132)-(buttons-1)*sc(12)-sc(38);
        const int name_y=agent.state==DECK_AGENT_WAITING?sc(16):sc(24);
        const lv_font_t *name_font=fit(&fq_font_dejavu_bold_28);
        glyph(lane,agent_icon(agent.id),sc(42),name_y+lv_font_get_line_height(name_font)/2,sc(30),agent.state==DECK_AGENT_IDLE?Muted:color);
        /* The name, then its state in smaller type on about the same baseline. */
        auto *title=clear_box(lane,sc(66),name_y,LV_SIZE_CONTENT,LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(title,LV_FLEX_FLOW_ROW);lv_obj_set_style_pad_column(title,sc(14),0);
        auto *name=label(title,agent.name,0,0,LV_SIZE_CONTENT,name_font,Text);
        char state[40];agent_state(agent,state,sizeof(state));
        auto *shown=lane_state[i]=label(title,state,0,0,LV_SIZE_CONTENT,fit(&fq_font_dejavu_20),agent.state==DECK_AGENT_IDLE?Muted:color);
        lv_obj_set_style_margin_top(shown,ascent(name)-ascent(shown)+1,0);
        bool fits=true;
        if(agent.state==DECK_AGENT_WAITING){
            /* A question is shown in full: nobody should allow what they cannot read. Three lines at 20 px, else
               smaller type; a question that still does not fit gets Deny only, and Claude asks in its own dialog. */
            auto *asked=label(lane,agent.text,sc(26),sc(62),text_w,fit(&fq_font_dejavu_20),Soft);
            lv_label_set_long_mode(asked,LV_LABEL_LONG_WRAP);lv_obj_set_height(asked,LV_SIZE_CONTENT);lv_obj_update_layout(asked);
            if(lv_obj_get_height(asked)>sc(76)){lv_obj_set_style_text_font(asked,small?&lv_font_montserrat_14:&fq_font_dejavu_16,0);lv_obj_update_layout(asked);}
            fits=lv_obj_get_height(asked)<=sc(80);lv_obj_set_height(asked,sc(80));
        } else {
            lane_text[i]=label(lane,agent_words(agent),sc(26),sc(68),text_w,fit(&fq_font_dejavu_20),agent.state==DECK_AGENT_IDLE?Dim:Soft);
            if(agent.sub[0]){  /* the project, behind a folder */
                glyph(lane,"lc:e0d7",sc(36),sc(113),sc(18),Dim);
                lane_sub[i]=label(lane,agent.sub,sc(54),sc(102),text_w-sc(28),fit(&fq_font_dejavu_20),Dim);
            }
        }
        const int right=ContentW-sc(20)-sc(132);
        if(asks){agent_button(lane,"Deny",right-sc(144),2,i,1);if(fits)agent_button(lane,"Allow",right,0,i,0);}
        else if(agent.state==DECK_AGENT_WAITING)agent_button(lane,"Open",right,1,i,3);  /* waiting in its own window: bring it forward */
        else if(agent.state==DECK_AGENT_WORKING){agent_button(lane,"Open",right-sc(144),1,i,3);agent_button(lane,"Stop",right,2,i,2);}
        else agent_button(lane,"Open",right,1,i,3);
    }
    if(!count){
        glyph(agents_area,"lc:e1bb",ContentW/2,sc(130),sc(72),Line);
        auto *empty=label(agents_area,"No agents are running",0,sc(190),ContentW,fit(&fq_font_dejavu_bold_24),Muted);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);
        auto *hint=label(agents_area,"Claude Code, Codex and ZCode show up here when they start",0,sc(230),ContentW,fit(&fq_font_dejavu_20),Dim);
        lv_obj_set_style_text_align(hint,LV_TEXT_ALIGN_CENTER,0);
    }
    char summary[32];
    if(waiting>1)snprintf(summary,sizeof(summary),"%d need you",waiting);
    else snprintf(summary,sizeof(summary),"%s",waiting?"One needs you":"Nobody is waiting");
    lv_label_set_text(agents_summary,summary);
    lv_obj_set_style_text_color(agents_summary,lv_color_hex(waiting?Amber:Muted),0);
    agents_version=agents_dot=version;agents_dirty=false;update_rail_dot();
}

/* ---- Mixer --------------------------------------------------------------------------------------- */
void draw_fader(int i) {
    const auto& fader=faders[i];
    const int fill=TrackH*fader.level/100,knob=sc(44);
    lv_obj_set_y(fader_fill[i],TrackH-fill);lv_obj_set_height(fader_fill[i],fill);
    lv_obj_set_hidden(fader_fill[i],fill<4);
    set_color(fader_fill[i],LV_STYLE_BG_COLOR,fader.muted?Line:fader.color);
    lv_obj_set_y(fader_knob[i],LV_CLAMP(0,TrackH-fill-knob/2,TrackH-knob));
    char text[12];
    if(fader.muted)snprintf(text,sizeof(text),"Muted");else snprintf(text,sizeof(text),"%d %%",fader.level);
    if(strcmp(lv_label_get_text(fader_value[i]),text))lv_label_set_text(fader_value[i],text);
    set_color(fader_mute[i],LV_STYLE_BG_COLOR,fader.muted?0x3A1D24:Card);
    set_color(fader_mute[i],LV_STYLE_BORDER_COLOR,fader.muted?Red:Line);
    if(fader_icon[i])set_color(fader_icon[i],LV_STYLE_TEXT_COLOR,fader.muted?0xFF8A8A:Muted);
}
void fader_touch(lv_event_t *event) {
    const int i=slot_of(event);
    auto *indev=lv_indev_active();
    if(i<0||i>=fader_count||!indev||deck_model_locked())return;
    lv_point_t point;lv_area_t area;
    lv_indev_get_point(indev,&point);lv_obj_get_coords(fader_zone[i],&area);
    int level=(area.y2-point.y)*100/(area.y2-area.y1);
    level=level<0?0:level>100?100:level;
    const bool released=lv_event_get_code(event)==LV_EVENT_RELEASED;
    fader_hold[i]=millis()+1500;faders_version=0;  /* the host's reading must not pull the knob back under the finger;
                                                   version 0: look again when the hold ends */
    if(level==faders[i].level&&!released)return;
    faders[i].level=static_cast<uint8_t>(level);draw_fader(i);
    if(!released&&millis()-fader_sent[i]<120)return;
    fader_sent[i]=millis();
    char line[96];
    snprintf(line,sizeof(line),"{\"type\":\"fader\",\"id\":\"%s\",\"level\":%d}",faders[i].id,level);
    deck_model_queue_line(line);
}
void mute_pressed(lv_event_t *event) {
    const int i=slot_of(event);
    if(i<0||i>=fader_count||deck_model_locked())return;
    faders[i].muted=!faders[i].muted;fader_hold[i]=millis()+1500;faders_version=0;draw_fader(i);
    char line[96];
    snprintf(line,sizeof(line),"{\"type\":\"mute\",\"id\":\"%s\"}",faders[i].id);
    deck_model_queue_line(line);
}
void build_faders() {
    lv_obj_clean(mixer_area);memset(fader_hold,0,sizeof(fader_hold));
    for(int i=0;i<fader_count;++i) {
        auto *card=box(mixer_area,0,0,FaderW,H-2*Top,sc(20),Card);  /* mixer_area's flex row places it */
        fader_value[i]=label(card,"",0,sc(18),FaderW,fit(&fq_font_dejavu_bold_24),Text);lv_obj_set_style_text_align(fader_value[i],LV_TEXT_ALIGN_CENTER,0);
        const int bar=sc(22),knob=sc(76),name_y=sc(64)+TrackH+sc(20),mute_y=name_y+sc(36),disc=sc(80);
        auto *zone=fader_zone[i]=clear_box(card,(FaderW-TrackW)/2,sc(64),TrackW,TrackH);lv_obj_set_clickable(zone,true);
        box(zone,(TrackW-bar)/2,0,bar,TrackH,bar/2,Bg);
        fader_fill[i]=box(zone,(TrackW-bar)/2,0,bar,TrackH,bar/2,faders[i].color);
        fader_knob[i]=box(zone,(TrackW-knob)/2,0,knob,sc(44),sc(12),Text);
        for(auto code:{LV_EVENT_PRESSED,LV_EVENT_PRESSING,LV_EVENT_RELEASED})lv_obj_add_event_cb(zone,fader_touch,code,slot_data(i));
        auto *name=label(card,faders[i].name,sc(4),name_y,FaderW-2*sc(4),fit(&fq_font_dejavu_20),Soft);lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);
        auto *mute=fader_mute[i]=lv_button_create(card);flat(mute,Card);
        lv_obj_set_pos(mute,(FaderW-disc)/2,mute_y);lv_obj_set_size(mute,disc,disc);lv_obj_set_style_radius(mute,disc/2,0);
        lv_obj_set_style_border_width(mute,2,0);
        fader_icon[i]=glyph(mute,faders[i].mic?"lc:e118":"lc:e1ab",disc/2-2,disc/2-2,sc(32),Muted);
        lv_obj_add_event_cb(mute,mute_pressed,LV_EVENT_CLICKED,slot_data(i));
        draw_fader(i);
    }
    if(!fader_count){auto *empty=label(mixer_area,"The PC has not sent its sound yet",0,sc(240),ContentW,fit(&fq_font_dejavu_20),Dim);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);
        lv_obj_set_ignore_layout(empty,true);}
}
void sync_faders() {
    deck_fader_t latest[DECK_FADERS_MAX]{};
    const int count=deck_model_faders(latest,DECK_FADERS_MAX);
    bool same=count==fader_count&&mixer_area&&lv_obj_get_child_count(mixer_area)>0;
    for(int i=0;same&&i<count;++i)same=!strcmp(latest[i].id,faders[i].id)&&!strcmp(latest[i].name,faders[i].name)&&latest[i].mic==faders[i].mic;
    const uint32_t now=millis();
    if(!same){memcpy(faders,latest,sizeof(faders));fader_count=count;build_faders();}
    bool held=false;
    if(same)for(int i=0;i<count;++i){
        if(fader_hold[i]&&static_cast<int32_t>(now-fader_hold[i])<0){held=true;continue;}
        fader_hold[i]=0;
        if(latest[i].level==faders[i].level&&latest[i].muted==faders[i].muted&&latest[i].color==faders[i].color)continue;
        faders[i]=latest[i];draw_fader(i);
    }
    faders_version=held?0:deck_model_faders_version();  /* 0: look again next tick, until the finger is gone */
}

/* ---- Status -------------------------------------------------------------------------------------- */
void draw_stat(int i,const deck_stat_t& stat) {
    if(strcmp(lv_label_get_text(stat_name[i]),stat.name))lv_label_set_text(stat_name[i],stat.name);
    if(strcmp(lv_label_get_text(stat_value[i]),stat.value))lv_label_set_text(stat_value[i],stat.value);
    if(strcmp(lv_label_get_text(stat_unit[i]),stat.unit))lv_label_set_text(stat_unit[i],stat.unit);
    set_color(stat_value[i],LV_STYLE_TEXT_COLOR,stat.color);
    set_color(stat_unit[i],LV_STYLE_TEXT_COLOR,mix(stat.color,Muted,.45f));
    const int fill=(StatW-2*sc(20))*stat.percent/100;
    lv_obj_set_width(stat_fill[i],fill);lv_obj_set_hidden(stat_fill[i],fill<3);
    set_color(stat_fill[i],LV_STYLE_BG_COLOR,stat.color);
    set_color(stat_card[i],LV_STYLE_BG_COLOR,stat.warn?WarnBg:Card);
}
void sync_stats() {
    deck_stat_t list[DECK_STATS_MAX]{};
    const int count=deck_model_stats(list,DECK_STATS_MAX);
    if(count!=stat_count) {
        lv_obj_clean(stats_area);stat_count=count;
        for(int i=0;i<count;++i) {
            const int inset=sc(20),inner=StatW-2*inset;
            auto *card=stat_card[i]=box(stats_area,0,0,StatW,StatH,sc(20),Card);  /* stats_area's flex wraps four to a row */
            stat_name[i]=label(card,"",inset,sc(18),inner,fit(&fq_font_dejavu_20),Muted);
            auto *row=clear_box(card,inset,sc(44),inner,sc(62));
            lv_obj_set_flex_flow(row,LV_FLEX_FLOW_ROW);lv_obj_set_flex_align(row,LV_FLEX_ALIGN_START,LV_FLEX_ALIGN_END,LV_FLEX_ALIGN_CENTER);
            lv_obj_set_style_pad_column(row,sc(6),0);
            stat_value[i]=lv_label_create(row);lv_label_set_text(stat_value[i],"");lv_obj_set_style_text_font(stat_value[i],small?&lv_font_montserrat_40:&lv_font_montserrat_48,0);
            stat_unit[i]=lv_label_create(row);lv_label_set_text(stat_unit[i],"");lv_obj_set_style_text_font(stat_unit[i],&fq_font_dejavu_16,0);
            lv_obj_set_style_pad_bottom(stat_unit[i],sc(9),0);
            auto *track=box(card,inset,StatH-sc(28),inner,sc(6),3,Bg);
            stat_fill[i]=box(track,0,0,0,sc(6),3,Accent);
        }
        if(!count){auto *empty=label(stats_area,"The PC has not sent its readings yet",0,sc(120),ContentW,fit(&fq_font_dejavu_20),Dim);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);
            lv_obj_set_ignore_layout(empty,true);}
    }
    const char *warned=nullptr;
    for(int i=0;i<count;++i){draw_stat(i,list[i]);if(list[i].warn&&!warned)warned=list[i].name;}
    char summary[40];
    if(warned)snprintf(summary,sizeof(summary),"%.15s is high",warned);else snprintf(summary,sizeof(summary),"%s",count?"All good":"");
    lv_label_set_text(stats_summary,summary);
    lv_obj_set_style_text_color(stats_summary,lv_color_hex(warned?Amber:Muted),0);
    stats_version=deck_model_stats_version();
}

/* ---- Rail and frame ------------------------------------------------------------------------------ */
/* The rail: one button per entry the host chose (screens and shortcuts to a page), at most seven. */
void refresh_rail() {
    if(!rail_items)return;
    const auto context=deck_model_context();
    int active=-1;
    for(int i=0;i<rail_count&&active<0;++i)
        if(rail_list[i].kind==4&&view==ViewKeys&&!strcmp(rail_list[i].profile,context.profile)&&!strcmp(rail_list[i].page,context.page))active=i;
    for(int i=0;i<rail_count&&active<0;++i)if(rail_list[i].kind<4&&rail_list[i].kind==view)active=i;
    for(int i=0;i<rail_count;++i) {
        lv_obj_set_style_bg_opa(rail_btn[i],i==active?LV_OPA_COVER:LV_OPA_TRANSP,0);
        if(rail_gl[i])lv_obj_set_style_text_color(rail_gl[i],lv_color_hex(i==active?Text:Dim),0);
    }
    if(rail_marker){lv_obj_set_hidden(rail_marker,active<0);if(active>=0)lv_obj_set_y(rail_marker,RailTop+active*RailPitch+sc(9));}
    update_rail_dot();
}
void set_view(int next) {
    if(next<0||next>=ViewCount)return;
    view=next;
    for(int i=0;i<ViewCount;++i)lv_obj_set_hidden(views[i],i!=view);
    if(view==ViewAgents&&(agents_dirty||agents_version!=deck_model_agents_version()))build_agents();
    refresh_rail();
}
/* A short light on a rail button that ran something, so the tap is seen. */
void flash_rail(int index) {
    auto *button=rail_btn[index];if(!button)return;
    lv_obj_set_style_bg_opa(button,LV_OPA_COVER,0);lv_obj_set_style_bg_color(button,lv_color_hex(OkBg),0);
    lv_timer_t *back=lv_timer_create([](lv_timer_t *timer){auto *target=static_cast<lv_obj_t*>(lv_timer_get_user_data(timer));
        if(lv_obj_is_valid(target)){lv_obj_set_style_bg_color(target,lv_color_hex(RailOn),0);refresh_rail();}lv_timer_delete(timer);},400,button);
    lv_timer_set_repeat_count(back,1);
}
void rail_pressed(lv_event_t *event) {
    const int index=slot_of(event);
    if(index<0||index>=rail_count||deck_model_locked())return;
    if(rail_list[index].kind>=4&&!deck_model_host_linked(HostTimeoutMs))return;  /* nobody on the PC would act on it */
    char line[40];
    snprintf(line,sizeof(line),"{\"type\":\"rail\",\"i\":%d}",index);
    if(rail_list[index].kind<4) {
        /* Which screen shows: the host reads the mixer often only for its screen, and counts the tap as activity. */
        char shown[32];snprintf(shown,sizeof(shown),"{\"type\":\"view\",\"v\":%d}",rail_list[index].kind);deck_model_queue_line(shown);
        /* Keys while the keys already show: back to the page before a shortcut (or the first page). Without
           this the tap changed nothing after a shortcut, and the keys button seemed dead. */
        if(rail_list[index].kind==ViewKeys&&view==ViewKeys)deck_model_queue_line(line);
        set_view(rail_list[index].kind);return;
    }
    deck_model_queue_line(line);
    if(rail_list[index].kind==5){flash_rail(index);return;}  /* runs steps on the PC: the screen stays */
    set_view(ViewKeys);
}
void build_rail() {
    deck_rail_item_t latest[DECK_RAIL_MAX]{};
    int count=deck_model_rail(latest,DECK_RAIL_MAX);
    rail_version=deck_model_rail_version();
    if(count==0)for(int k=0;k<4;++k)latest[count++].kind=static_cast<uint8_t>(k);  /* an older host: the four screens */
    bool has_keys=false;for(int i=0;i<count;++i)has_keys=has_keys||latest[i].kind==0;
    if(!has_keys&&count<DECK_RAIL_MAX){memmove(&latest[1],&latest[0],sizeof(latest[0])*static_cast<size_t>(count));latest[0]=deck_rail_item_t{};++count;}
    memcpy(rail_list,latest,sizeof(rail_list));rail_count=count;rail_agents=-1;
    lv_obj_clean(rail_items);memset(rail_btn,0,sizeof(rail_btn));memset(rail_gl,0,sizeof(rail_gl));
    rail_marker=box(rail_items,0,RailTop+sc(9),sc(4),sc(36),sc(2),Accent);
    const int x=sc(15),size=sc(54);
    for(int i=0;i<count;++i) {
        auto *button=rail_btn[i]=lv_button_create(rail_items);flat(button,RailOn);
        lv_obj_set_pos(button,x,RailTop+i*RailPitch);lv_obj_set_size(button,size,size);lv_obj_set_style_radius(button,sc(16),0);
        const char *icon=rail_list[i].kind<4?ViewIcons[rail_list[i].kind]:rail_list[i].icon;
        rail_gl[i]=glyph(button,icon,size/2,size/2,sc(28),Dim);
        if(!rail_gl[i])rail_gl[i]=glyph(button,ViewIcons[0],size/2,size/2,sc(28),Dim);
        lv_obj_add_event_cb(button,rail_pressed,LV_EVENT_CLICKED,slot_data(i));
        if(rail_list[i].kind==ViewAgents)rail_agents=i;
    }
    rail_dot=rail_agents>=0?box(rail_items,x+size-sc(13),RailTop+rail_agents*RailPitch+sc(3),sc(12),sc(12),sc(6),Amber):nullptr;
    refresh_rail();
}
void hide_when_linked(lv_obj_t *object,int32_t linked) {lv_obj_set_hidden(object,linked==1);}
void dim_when_unlinked(lv_obj_t *area,int32_t linked) {lv_obj_set_style_opa(area,linked==1?LV_OPA_COVER:LV_OPA_40,0);}
/* A card over a cockpit screen, and the screen dimmed, while the PC does not answer. */
void add_offline_card(lv_obj_t *area) {
    const int width=sc(600);
    auto *card=box(lv_obj_get_parent(area),Pad+(ContentW-width)/2,H/2-sc(80),width,sc(150),sc(22),WarnBg);
    lv_obj_set_style_border_width(card,2,0);lv_obj_set_style_border_color(card,lv_color_hex(Amber),0);
    auto *title=label(card,"PC not connected",0,sc(34),width,fit(&fq_font_dejavu_bold_28),Amber);lv_obj_set_style_text_align(title,LV_TEXT_ALIGN_CENTER,0);
    auto *hint=label(card,"Start Tessera on the PC, or check the USB cable",0,sc(86),width,fit(&fq_font_dejavu_20),Soft);lv_obj_set_style_text_align(hint,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_bind_int(card,link_subject,hide_when_linked);lv_obj_bind_int(area,link_subject,dim_when_unlinked);
}
/* ---- About sheet: a long press on the logo shows the firmware, the PC link and a brightness slider. ---- */
lv_obj_t *about=nullptr;
void close_about() {if(about)lv_obj_delete(about);about=nullptr;}
void show_link(lv_obj_t *line,int32_t linked) {
    lv_label_set_text(line,linked==1?"PC connected":"PC not connected");set_color(line,LV_STYLE_TEXT_COLOR,linked==1?Accent:Amber);
}
void about_tapped(lv_event_t *event) {if(lv_event_get_target(event)==about)close_about();}  /* outside the card */
void brightness_moved(lv_event_t *event) {
    auto *slider=static_cast<lv_obj_t*>(lv_event_get_target(event));
    /* Every step lights the panel; the level is saved (and the host told) once, when the finger lifts. */
    deck_model_request_brightness(lv_slider_get_value(slider),lv_event_get_code(event)==LV_EVENT_RELEASED);
}
void open_about(lv_event_t *) {
    if(about||deck_model_locked())return;
    about=lv_obj_create(screen);flat(about,Bg);lv_obj_set_style_bg_opa(about,LV_OPA_70,0);lv_obj_set_pos(about,0,0);lv_obj_set_size(about,W,H);
    lv_obj_add_event_cb(about,about_tapped,LV_EVENT_CLICKED,nullptr);
    const int CardW=sc(460),left=sc(28);
    auto *card=box(about,Rail+sc(16),sc(16),CardW,sc(300),sc(22),Card);lv_obj_set_clickable(card,true);
    lv_obj_set_style_border_width(card,2,0);lv_obj_set_style_border_color(card,lv_color_hex(Line),0);
    label(card,"Tessera",left,sc(24),CardW-2*left,fit(&fq_font_dejavu_bold_28),Text);
    char version[48];snprintf(version,sizeof(version),"Firmware %s",firmware_version);
    label(card,version,left,sc(70),CardW-2*left,fit(&fq_font_dejavu_20),Soft);
    lv_obj_bind_int(label(card,"",left,sc(102),CardW-2*left,fit(&fq_font_dejavu_20),Accent),link_subject,show_link);
    /* The slider and the percentage share one subject: a drag updates the number with no code of ours. */
    lv_subject_set_int(brightness_subject,deck_model_brightness());
    label(card,"Brightness",left,sc(166),CardW-sc(160),fit(&fq_font_dejavu_20),Soft);
    auto *level=label(card,"",CardW-sc(128),sc(166),sc(100),fit(&fq_font_dejavu_20),Text);lv_obj_set_style_text_align(level,LV_TEXT_ALIGN_RIGHT,0);
    lv_label_bind_text(level,brightness_subject,"%d %%");
    auto *slider=lv_slider_create(card);lv_obj_set_pos(slider,sc(40),sc(224));lv_obj_set_size(slider,CardW-sc(80),sc(20));
    lv_slider_set_range(slider,1,100);lv_slider_bind_value(slider,brightness_subject);
    lv_obj_set_style_bg_color(slider,lv_color_hex(Line),LV_PART_MAIN);lv_obj_set_style_bg_color(slider,lv_color_hex(Accent),LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(slider,lv_color_hex(Text),LV_PART_KNOB);lv_obj_set_style_pad_all(slider,sc(10),LV_PART_KNOB);
    lv_obj_set_ext_click_area(slider,sc(20));  /* a fingertip, not a 20 px bar */
    for(auto code:{LV_EVENT_VALUE_CHANGED,LV_EVENT_RELEASED})lv_obj_add_event_cb(slider,brightness_moved,code,nullptr);
}

/* ---- Panel lock: the logo turns into a lock badge; holding it LockHoldMs unlocks and tells the host. ---- */
lv_obj_t *logo=nullptr,*lock_badge=nullptr,*lock_ring=nullptr;
uint32_t lock_pressed_at=0;
void lock_touched(lv_event_t *) {lock_pressed_at=millis();}
void update_lock() {
    const int locked=deck_model_locked()?1:0;
    if(locked&&lv_subject_get_int(lock_subject)!=1)close_about();
    lv_subject_set_int(lock_subject,locked);  /* the logo and the lock badge follow */
    const bool holding=locked&&lv_obj_has_state(lock_badge,LV_STATE_PRESSED);
    const uint32_t held=holding?millis()-lock_pressed_at:0;
    lv_arc_set_value(lock_ring,static_cast<int32_t>(held>=LockHoldMs?100:held*100/LockHoldMs));
    if(held<LockHoldMs)return;
    deck_model_set_locked(false);deck_model_queue_line("{\"type\":\"unlocked\"}");
    for(auto *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_wait_release(indev);  /* the same touch must not tap what shows next */
}

void update_link() {
    const int linked=deck_model_host_linked(HostTimeoutMs)?1:0;
    if(linked==lv_subject_get_int(link_subject))return;
    lv_subject_set_int(link_subject,linked);  /* the rail's NO PC, the About line, the offline cards and the dimming follow */
    if(linked){agents_dirty=true;sync_stats();return;}
    for(auto *summary:{agents_summary,stats_summary}){lv_label_set_text(summary,"PC not connected");lv_obj_set_style_text_color(summary,lv_color_hex(Amber),0);}
}
/* Title on the left, a one-line summary on the right. */
lv_obj_t *head(lv_obj_t *parent,const char *title,lv_obj_t **summary) {
    auto *name=label(parent,title,Pad,Top-sc(2),ContentW/2,fit(&fq_font_dejavu_bold_28),Text);
    *summary=label(parent,"",Pad+ContentW/2,0,ContentW/2,fit(&fq_font_dejavu_20),Muted);
    lv_obj_set_y(*summary,Top-sc(2)+ascent(name)-ascent(*summary));  /* on the title's baseline */
    lv_obj_set_style_text_align(*summary,LV_TEXT_ALIGN_RIGHT,0);
    return name;
}
uint32_t mix(uint32_t from,uint32_t to,float t) {
    auto channel=[&](int shift){return static_cast<uint32_t>(((from>>shift)&0xFF)+(static_cast<int>((to>>shift)&0xFF)-static_cast<int>((from>>shift)&0xFF))*t+.5f)&0xFF;};
    return channel(16)<<16|channel(8)<<8|channel(0);
}
/* The clock's tiles: the same hue, pushed away from grey so it reads deeper without going dark. */
uint32_t vivid(uint32_t c) {
    const float r=(c>>16)&0xFF,g=(c>>8)&0xFF,b=c&0xFF,grey=.3f*r+.59f*g+.11f*b;
    auto push=[&](float v){v=grey+(v-grey)*1.6f;return static_cast<uint32_t>(v<0?0:v>255?255:v+.5f);};
    return push(r)<<16|push(g)<<8|push(b);
}
/* The brand gradient: mint -> cyan -> purple, t in 0..1. */
uint32_t sweep(float t) {return t<.5f?mix(Accent,Cyan,t*2):mix(Cyan,Purple,(t-.5f)*2);}

/* The Tessera mark: a 3x3 mosaic on the brand gradient; the top-right tile has broken loose. */
void make_logo(lv_obj_t *parent,int x,int y) {
    const int Tile=sc(13),Space=sc(3);
    for(int row=0;row<3;++row)for(int col=0;col<3;++col) {
        if(row==0&&col==2)continue;
        box(parent,x+col*(Tile+Space),y+sc(4)+row*(Tile+Space),Tile,Tile,sc(4),sweep((row+col)/4.f));
    }
    box(parent,x+sc(34),y,sc(12),sc(12),sc(4),Amber);
}

/* ---- Ambient clock: a big clock built from brand-gradient tiles, the date and a host-supplied line. ---- */
lv_obj_t *ambient,*ambient_clock,*ambient_date,*ambient_line,*ambient_icon;
const char *weather_shown="";  /* the icon on the clock now, for the tests */
/* The host sends words ("12 C, Light rain - Oslo"), not a code: the first word that matches picks the icon.
 * Precipitation goes before cloud, so "Rain showers" is rain and "Snow showers" is snow; the host adds "night"
 * after sunset at the place, so a clear night shows the moon. */
void show_weather_icon(const char *line) {
    static const struct {const char *word,*icon;uint32_t color;} Icons[]={{"thunder","lc:e08c",Purple},{"hail","lc:e08b",Text},
        {"snow","lc:e090",Text},{"drizzle","lc:e08a",Cyan},{"rain","lc:e08e",Cyan},{"shower","lc:e08e",Cyan},
        {"fog","lc:e214",Soft},{"overcast","lc:e088",Soft},{"cloudy night","lc:e215",Text},{"night","lc:e11e",Text},{"cloud","lc:e216",Amber},{"clear","lc:e178",Amber}};
    char lower[DECK_AMBIENT_MAX+1];size_t n=0;
    for(;n<DECK_AMBIENT_MAX&&line[n];++n)lower[n]=static_cast<char>(tolower(static_cast<unsigned char>(line[n])));
    lower[n]='\0';
    if(char *city=strstr(lower," - "))*city='\0';  /* "12 C, Light rain - Oslo": the place is not the weather */
    char packed[5]{};weather_shown="";
    for(const auto& item:Icons)if(strstr(lower,item.word)&&deck_lucide_glyph(item.icon,packed)){set_color(ambient_icon,LV_STYLE_TEXT_COLOR,item.color);weather_shown=item.icon;break;}
    lv_label_set_text(ambient_icon,packed);
    lv_obj_set_hidden(ambient_icon,!packed[0]);
}
char ambient_time[12]="";uint32_t ambient_seen=0;lv_obj_t *ambient_meridiem=nullptr;
const char *const DigitGlyphs[11][7]={
    {"01110","10001","10011","10101","11001","10001","01110"},{"00100","01100","00100","00100","00100","00100","01110"},
    {"01110","10001","00001","00010","00100","01000","11111"},{"11110","00001","00001","01110","00001","00001","11110"},
    {"00010","00110","01010","10010","11111","00010","00010"},{"11111","10000","11110","00001","00001","10001","01110"},
    {"00110","01000","10000","11110","10001","10001","01110"},{"11111","00001","00010","00100","01000","01000","01000"},
    {"01110","10001","10001","01110","10001","10001","01110"},{"01110","10001","10001","01111","00001","00010","01100"},
    {"0","0","1","0","1","0","0"}};
void draw_big_clock(const char *text,const char *meridiem) {
    const bool twelve=meridiem[0]!='\0';
    const int Dot=sc(twelve?32:36),Pitch=sc(twelve?37:42),Space=sc(twelve?24:28),Gap=sc(20);  /* Gap: digits to AM/PM */
    lv_obj_clean(ambient_clock);
    lv_label_set_text(ambient_meridiem,meridiem);lv_obj_update_layout(ambient_meridiem);
    const int suffix=twelve?Gap+lv_obj_get_width(ambient_meridiem):0;
    int glyphs=0;for(const char *c=text;*c;++c)++glyphs;
    /* Two passes: measure the tiles that are lit (a "1" leaves its outer columns empty), then draw them centred. */
    int left=W,right=0;
    auto tiles=[&](int x0,bool draw) {
        int x=x0,index=0;
        for(const char *c=text;*c;++c,++index) {
            const int digit=*c==':'?10:(*c>='0'&&*c<='9'?*c-'0':-1);
            const int columns=*c==':'?1:5;
            if(digit>=0)for(int row=0;row<7;++row)for(int col=0;col<columns;++col) {
                if(DigitGlyphs[digit][row][col]!='1')continue;
                const int at=x+col*Pitch;
                if(draw)box(ambient_clock,at,row*Pitch,Dot,Dot,sc(7),vivid(sweep((index+col/5.f)/(glyphs>0?glyphs:1))));
                else{if(at<left)left=at;if(at+Dot>right)right=at+Dot;}
            }
            x+=columns*Pitch-(Pitch-Dot)+Space;
        }
    };
    tiles(0,false);
    const int shift=(W-(right-left)-suffix)/2-left;
    tiles(shift,true);
    lv_obj_set_pos(ambient_meridiem,right+shift+Gap,lv_obj_get_y(ambient_clock)+7*Pitch-(Pitch-Dot)-ascent(ambient_meridiem)-sc(9));  /* on the digits' baseline */
}
lv_obj_t *boot=nullptr;  /* the boot screen, while it plays */
void show_ambient(bool on) {
    if(!ambient||on==(deck_model_screen()==DECK_SCREEN_AMBIENT))return;
    deck_model_set_screen(on?DECK_SCREEN_AMBIENT:DECK_SCREEN_DECK);
    if(on){ambient_time[0]='\0';ambient_seen=0;}
    if(!boot)lv_screen_load(on?ambient:screen);  /* the boot screen loads the one asked for when it ends */
}
void ambient_touched(lv_event_t *) {
    if(deck_model_screen()!=DECK_SCREEN_AMBIENT)return;
    show_ambient(false);deck_model_note_touch_return();deck_model_request_wake();
}
void build_ambient() {
    ambient=lv_obj_create(nullptr);flat(ambient,Bg);
    ambient_clock=box(ambient,0,sc(80),W,7*sc(42),0,Bg);
    ambient_meridiem=label(ambient,"",0,0,LV_SIZE_CONTENT,fit(&fq_font_dejavu_bold_40),Soft);
    ambient_date=label(ambient,"",0,sc(404),W,fit(&fq_font_dejavu_bold_40),Text);lv_obj_set_style_text_align(ambient_date,LV_TEXT_ALIGN_CENTER,0);
    /* The weather: an icon and the host's line side by side, centred together. */
    auto *row=clear_box(ambient,0,sc(466),W,LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row,LV_FLEX_FLOW_ROW);lv_obj_set_flex_align(row,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(row,sc(16),0);
    ambient_icon=label(row,"",0,0,60,&deck_lucide_60,Soft);lv_obj_set_style_text_align(ambient_icon,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(ambient_icon,true);
    ambient_line=label(row,"",0,0,LV_SIZE_CONTENT,fit(&fq_font_dejavu_28),Soft);lv_obj_set_style_max_width(ambient_line,W-sc(200),0);
    lv_label_set_long_mode(ambient_line,LV_LABEL_LONG_WRAP);  /* a long weather line wraps */
    lv_obj_add_event_cb(ambient,ambient_touched,LV_EVENT_PRESSED,nullptr);
}
void update_ambient() {
    const int request=deck_model_take_screen_request();
    if(request==DECK_SCREEN_AMBIENT)show_ambient(true);else if(request==DECK_SCREEN_DECK)show_ambient(false);
    if(deck_model_screen()!=DECK_SCREEN_AMBIENT)return;
    const char *now=time_service_time_text();
    char shown[sizeof(ambient_time)];snprintf(shown,sizeof(shown),"%s%s",now,time_service_meridiem());  /* "12:00" AM and PM differ */
    if(strcmp(shown,ambient_time)){snprintf(ambient_time,sizeof(ambient_time),"%s",shown);draw_big_clock(now,time_service_meridiem());lv_label_set_text(ambient_date,time_service_date_text());}
    /* One version read before the copy: a line that lands after it bumps the version again and is drawn next tick. */
    const uint32_t version=deck_model_ambient_version();
    if(ambient_seen!=version){char line[DECK_AMBIENT_MAX+1];deck_model_ambient(line,sizeof(line));lv_label_set_text(ambient_line,line);show_weather_icon(line);ambient_seen=version;}
}

/* ---- Boot: the mark builds itself and its amber tile breaks loose, the wordmark switches on column by column, then
 * the logo fades out and the keys replace it. One object draws the logo, so each frame redraws only that strip. ---- */
const char *const WordGlyphs[7][7]={  /* TESSERA on the clock's 5 x 7 grid, as in docs/images/logo.svg */
    {"11111","00100","00100","00100","00100","00100","00100"},{"11111","10000","10000","11110","10000","10000","11111"},
    {"01111","10000","10000","01110","00001","00001","11110"},{"01111","10000","10000","01110","00001","00001","11110"},
    {"11111","10000","10000","11110","10000","10000","11111"},{"11110","10001","10001","11110","10100","10010","10001"},
    {"01110","10001","10001","11111","10001","10001","10001"}};
constexpr int32_t BootWordMs=700,BootOutMs=1250,BootEndMs=1400;
constexpr int BootMargin=6;  /* around the logo's box, for the tiles' overshoot */
constexpr uint32_t BootFoot=0x465258;  /* the version line: there if you look, quieter than any real text */
lv_obj_t *boot_version=nullptr;int32_t boot_ms=0;
float progress(int32_t t,int32_t from,int32_t to) {return t<=from?0:t>=to?1:static_cast<float>(t-from)/(to-from);}
float ease_out(float t) {return 1-(1-t)*(1-t)*(1-t);}
float ease_in_out(float t) {return t<.5f?4*t*t*t:1-std::pow(2-2*t,3.f)/2;}
float back_out(float t) {t-=1;return 1+2.6f*t*t*t+1.6f*t*t;}  /* overshoots by about 9% before it settles */
void boot_draw(lv_event_t *event) {
    const int32_t t=boot_ms;const float shown=1-ease_in_out(progress(t,BootOutMs,BootEndMs));  /* fades to the background */
    if(shown<=0)return;
    lv_layer_t *layer=lv_event_get_layer(event);lv_area_t area;lv_obj_get_coords(lv_event_get_current_target_obj(event),&area);
    /* The logo's 308 x 60 box at two pixels a unit, laid on whole pixels like the clock: every dot the same size and gap. */
    const float u=2*scale;const int left=area.x1+sc(BootMargin),top=area.y1+sc(BootMargin);
    auto px=[&](float units){return static_cast<int>(std::lround(units*u));};
    lv_draw_rect_dsc_t dsc;lv_draw_rect_dsc_init(&dsc);
    auto square=[&](float cx,float cy,float size,float radius,uint32_t color) {  /* `size` pixels wide, centred on (cx, cy) */
        if(size<1)return;
        const auto x1=static_cast<int32_t>(std::lround(cx-size/2)),y1=static_cast<int32_t>(std::lround(cy-size/2)),side=static_cast<int32_t>(std::lround(size));
        const lv_area_t at={x1,y1,x1+side-1,y1+side-1};
        dsc.bg_color=lv_color_hex(mix(Bg,color,shown));dsc.radius=static_cast<int32_t>(std::lround(LV_MIN(radius,size/2)));
        lv_draw_rect(layer,&dsc,&at);
    };
    /* The mark: eight tiles pop in one after another, then the amber one pops into the grid and breaks loose. */
    const int pitch=px(16),tile=pitch-px(3);
    for(int i=0;i<8;++i) {
        const int cell=i<2?i:i+1,row=cell/3,col=cell%3;const float k=back_out(progress(t,50+i*40,350+i*40));
        square(left+px(4)+col*pitch+tile/2.f,top+px(8)+row*pitch+tile/2.f,tile*k,px(4)*k,sweep((row+col)/4.f));
    }
    const float k=back_out(progress(t,370,670)),loose=ease_out(progress(t,720,870)),amber=px(12);
    square(left+px(36+2*loose)+amber/2,top+px(8-4*loose)+amber/2,amber*k,px(4)*k,Amber);
    /* The wordmark: its columns switch on left to right while the amber tile settles. */
    const int step=px(6),dot=step-px(1),letter_step=5*step+px(2);
    for(int letter=0;letter<7;++letter)for(int col=0;col<5;++col) {
        const float along=(32*letter+6*col)/216.f;
        if(t<BootWordMs+static_cast<int32_t>(along*350))continue;
        const float x=left+px(82)+letter*letter_step+col*step+dot/2.f;
        for(int row=0;row<7;++row)if(WordGlyphs[letter][row][col]=='1')square(x,top+px(9)+row*step+dot/2.f,dot,px(2),sweep(along));
    }
}
void boot_frame(void *logo,int32_t ms) {
    boot_ms=ms;lv_obj_invalidate(static_cast<lv_obj_t*>(logo));
    if(boot_version)set_color(boot_version,LV_STYLE_TEXT_COLOR,mix(Bg,BootFoot,progress(ms,BootWordMs,BootWordMs+200)*(1-ease_in_out(progress(ms,BootOutMs,BootEndMs)))));
}
void boot_done(lv_anim_t *) {
    /* The logo has faded to the background, so the keys simply replace it: a fade would redraw the whole screen twice a
     * step, four or five visible jumps on the panel. The ambient clock wins if the host asked for it meanwhile. */
    lv_obj_t *old=boot;boot=boot_version=nullptr;
    lv_screen_load(deck_model_screen()==DECK_SCREEN_AMBIENT?ambient:screen);lv_obj_delete_async(old);
}

/* ---- Notice: a short message from the host (AD_NOTIFY) on the top layer, over whichever screen shows. Only the banner
 * takes touches, and a tap on it closes it. A new message replaces the one on show; one that arrives while the boot
 * screen plays waits for it to end. ---- */
constexpr uint32_t NoticeColors[]={Cyan,Accent,Amber,Red};  /* info, ok, warn, error */
lv_obj_t *notice=nullptr;uint32_t notice_until=0;
void close_notice() {if(notice)lv_obj_delete(notice);notice=nullptr;}
void notice_tapped(lv_event_t *) {if(notice)lv_obj_delete_async(notice);notice=nullptr;}  /* not inside its own event */
void show_notice(const char *text,int level,int seconds) {
    close_notice();
    /* inset: above and below the text, so one line stays over the header and leaves the keys clear */
    const int width=sc(680),inset=sc(14),side=sc(18),border=2,mark=sc(6),text_x=side+mark+sc(16),text_w=width-2*border-text_x-side;
    const lv_font_t *font=fit(&fq_font_dejavu_24);const int line=lv_font_get_line_height(font);
    notice=box(lv_layer_top(),(W-width)/2,sc(8),width,line,sc(16),Card);lv_obj_set_clickable(notice,true);
    lv_obj_set_style_border_width(notice,border,0);lv_obj_set_style_border_color(notice,lv_color_hex(Line),0);
    /* The text is the host's: set as it is, never formatted. One or two lines; a longer one ends in dots. */
    auto *words=label(notice,text,text_x,inset,text_w,font,Text);
    lv_label_set_long_mode(words,LV_LABEL_LONG_WRAP);lv_obj_set_height(words,LV_SIZE_CONTENT);lv_obj_update_layout(words);
    const int text_h=LV_MIN(lv_obj_get_height(words),2*line);
    if(lv_obj_get_height(words)>text_h){lv_label_set_long_mode(words,LV_LABEL_LONG_DOT);lv_obj_set_height(words,text_h);}
    lv_obj_set_height(notice,text_h+2*inset+2*border);
    box(notice,side,inset,mark,text_h,mark/2,NoticeColors[level>=0&&level<4?level:0]);  /* the level's colored edge */
    lv_obj_add_event_cb(notice,notice_tapped,LV_EVENT_CLICKED,nullptr);
    notice_until=millis()+static_cast<uint32_t>(seconds)*1000;
}
void update_notice() {
    if(notice&&static_cast<int32_t>(millis()-notice_until)>=0)close_notice();
    char text[DECK_NOTICE_MAX+1];int level=0,seconds=0;
    if(!boot&&deck_model_take_notice(text,sizeof(text),&level,&seconds))show_notice(text,level,seconds);
}

int view_before_question=-1;  /* the screen a permission question took the panel away from */
bool question_waiting() {
    deck_agent_t list[DECK_AGENTS_MAX];const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    for(int i=0;i<count;++i)if(list[i].state==DECK_AGENT_WAITING&&list[i].asks)return true;
    return false;
}
void update(lv_timer_t*) {
    if(button_version!=deck_model_buttons_version())build_keys();
    else {
        /* Compare the insert generation, not the count: a full cache evicts one image per insert. */
        if(image_missing&&deck_image_generation()!=image_generation)fill_images();
        if(live_version!=deck_model_live_version())update_live();
    }
    if(context_version!=deck_model_context_version())update_context();
    if(rail_version!=deck_model_rail_version())build_rail();
    if(agents_dirty||agents_version!=deck_model_agents_version()){
        if(view==ViewAgents)build_agents();
        else if(agents_dot!=deck_model_agents_version()){agents_dot=deck_model_agents_version();update_rail_dot();}
    }
    const int wanted=deck_model_take_view_request();
    if(wanted>=0){if(wanted==ViewAgents&&view!=ViewAgents)view_before_question=view;set_view(wanted);}
    if(view_before_question>=0&&view!=ViewAgents)view_before_question=-1;  /* you left the agents screen yourself */
    if(view_before_question>=0&&agents_version==deck_model_agents_version()&&!question_waiting()){
        if(view==ViewAgents)set_view(view_before_question);  /* answered or gone: back to the screen you had */
        view_before_question=-1;
    }
    for(auto& hold:fader_hold)if(hold&&static_cast<int32_t>(millis()-hold)>=0)hold=0;
    if(faders_version!=deck_model_faders_version())sync_faders();
    if(stats_version!=deck_model_stats_version())sync_stats();
    const bool keys_seen=view==ViewKeys&&deck_model_screen()==DECK_SCREEN_DECK&&!deck_model_dimmed();
    if(keys_seen)for(auto& image:images)if(image.image&&image.image->frames.size()>1&&static_cast<int32_t>(millis()-image.due)>=0){image.frame=(image.frame+1)%image.image->frames.size();image_frame(image);}
    int id=0;deck_feedback_t result;
    while(deck_model_take_feedback(&id,&result)){
        if(id<1||id>DECK_MAX_BUTTONS)continue;
        awaiting[id]=false;if(stale[id]){stale[id]=false;continue;}
        for(int i=0;i<DECK_MAX_BUTTONS;++i)if(ids[i]==id&&keys[i])flash(i,result==DECK_FEEDBACK_ALERT?AlertBg:OkBg,500);
    }
    for(int i=0;i<DECK_MAX_BUTTONS;++i)if(flash_until[i]&&keys[i]&&static_cast<int32_t>(millis()-flash_until[i])>=0){lv_anim_delete(keys[i],pulse_opa);lv_obj_set_style_bg_opa(keys[i],LV_OPA_COVER,0);lv_obj_set_style_bg_color(keys[i],lv_color_hex(base_bg[i]),0);flash_until[i]=0;}
    confirm_tick();
    update_link();
    update_lock();
    update_ambient();
    update_notice();
    /* Runs every 40 ms: only touch the label when the minute changed. */
    const char *clock_now=time_service_time_text();
    if(strcmp(lv_label_get_text(clock_label),clock_now))lv_label_set_text(clock_label,clock_now);
}
}

extern "C" void ui_init(void) {
    W=lv_display_get_horizontal_resolution(nullptr);H=lv_display_get_vertical_resolution(nullptr);
    scale=LV_MIN(W/1024.f,H/600.f);small=scale<.9f;
    Rail=sc(84);Pad=sc(26);Top=sc(22);HeadH=sc(50);RailTop=sc(84);RailPitch=sc(60);ContentW=W-Rail-2*Pad;
    FaderGap=sc(18);FaderW=(ContentW-4*FaderGap)/5;TrackW=sc(110);TrackH=H-2*Top-sc(216);
    StatGap=sc(14);StatW=(ContentW-3*StatGap)/4;StatH=sc(156);
    init_styles();
    link_subject=lv_subject_create(LV_SUBJECT_TYPE_INT);lv_subject_set_int(link_subject,-1);
    lock_subject=lv_subject_create(LV_SUBJECT_TYPE_INT);
    brightness_subject=lv_subject_create(LV_SUBJECT_TYPE_INT);
    screen=lv_obj_create(nullptr);flat(screen,Bg);
    for(int i=0;i<ViewCount;++i)views[i]=clear_box(screen,Rail,0,W-Rail,H);
    /* Keys */
    page_label=head(views[ViewKeys],"Main",&profile_label);
    keys_area=clear_box(views[ViewKeys],Pad,Top+HeadH,ContentW,H-Top-HeadH-Top);
    /* Swipes end here (keys bubble them up); clickable so a swipe may start between keys too. */
    lv_obj_set_clickable(keys_area,true);lv_obj_set_gesture_bubble(keys_area,false);
    lv_obj_add_event_cb(keys_area,swipe,LV_EVENT_GESTURE,nullptr);
    /* Agents */
    head(views[ViewAgents],"Agents",&agents_summary);
    agents_area=clear_box(views[ViewAgents],Pad,Top+HeadH,ContentW,H-Top-HeadH);
    /* Mixer: no heading, the faders take the whole height */
    mixer_area=clear_box(views[ViewMixer],Pad,Top,ContentW,H-2*Top);
    lv_obj_set_flex_flow(mixer_area,LV_FLEX_FLOW_ROW);lv_obj_set_style_pad_column(mixer_area,FaderGap,0);
    /* Status: four cards to a row (4 x StatW and 3 gaps fit ContentW), the rest wrap below */
    head(views[ViewStatus],"This PC",&stats_summary);
    stats_area=clear_box(views[ViewStatus],Pad,Top+HeadH,ContentW,H-Top-HeadH);
    lv_obj_set_flex_flow(stats_area,LV_FLEX_FLOW_ROW_WRAP);lv_obj_set_style_pad_column(stats_area,StatGap,0);lv_obj_set_style_pad_row(stats_area,StatGap,0);
    /* Rail */
    auto *rail=box(screen,0,0,Rail,H,0,RailBg);
    logo=clear_box(rail,0,sc(8),Rail,sc(68));make_logo(logo,(Rail-sc(46))/2,sc(12));lv_obj_set_clickable(logo,true);
    lv_obj_add_event_cb(logo,open_about,LV_EVENT_LONG_PRESSED,nullptr);
    const int side=sc(54);
    lock_badge=lv_button_create(rail);flat(lock_badge,RailOn);lv_obj_set_pos(lock_badge,sc(15),sc(14));lv_obj_set_size(lock_badge,side,side);
    lv_obj_set_style_radius(lock_badge,side/2,0);lv_obj_add_event_cb(lock_badge,lock_touched,LV_EVENT_PRESSED,nullptr);
    if(!glyph(lock_badge,"lc:e10b",side/2,side/2,sc(26),Amber)){auto *mark=label(lock_badge,"L",0,sc(15),side,&fq_font_dejavu_bold_20,Amber);lv_obj_set_style_text_align(mark,LV_TEXT_ALIGN_CENTER,0);}
    lock_ring=make_ring(lock_badge,side,sc(3),Amber,Accent,0);
    lv_obj_bind_bool(logo,lock_subject,lv_obj_set_hidden);
    lv_obj_bind_int(lock_badge,lock_subject,[](lv_obj_t *badge,int32_t locked){lv_obj_set_hidden(badge,locked!=1);});
    rail_items=clear_box(rail,0,0,Rail,H);
    /* Bold 20 is too wide for a narrower rail. */
    link_label=label(rail,"NO PC",0,H-sc(74),Rail,small?&fq_font_dejavu_16:&fq_font_dejavu_bold_20,Amber);lv_obj_set_style_text_align(link_label,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_bind_int(link_label,link_subject,hide_when_linked);
    clock_label=label(rail,"--:--",0,H-sc(44),Rail,fit(&fq_font_dejavu_20),Soft);lv_obj_set_style_text_align(clock_label,LV_TEXT_ALIGN_CENTER,0);
    for(lv_indev_t *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_add_event_cb(indev,wake_touch,LV_EVENT_PRESSED,nullptr);
    build_ambient();
    build_keys();build_rail();update_context();build_agents();sync_faders();sync_stats();set_view(ViewKeys);
    for(auto *area:{agents_area,mixer_area,stats_area})add_offline_card(area);
    update_link();
    lv_screen_load(screen);update(nullptr);lv_timer_create(update,40,nullptr);
}
/* Names are user text: a quote or backslash must not break the JSON of the status line. */
static void json_escape(const char *in,char *out,size_t size) {
    size_t n=0;
    for(;*in&&n+2<size;++in){if(*in=='"'||*in=='\\')out[n++]='\\';out[n++]=*in;}
    out[n]='\0';
}
extern "C" int ui_debug_visible_text(char *out,size_t size) {
    if(!out||!size)return -1;
    const auto context=deck_model_context();
    char profile[2*sizeof(context.profile)],page[2*sizeof(context.page)];
    json_escape(context.profile,profile,sizeof(profile));json_escape(context.page,page,sizeof(page));
    const int n=snprintf(out,size,"{\"screen\":\"%s\",\"view\":\"%s\",\"buttons\":%d,\"profile\":\"%s\",\"page\":\"%s\",\"canBack\":%s,\"pc\":%s,\"weather\":\"%s\"}",
                         deck_model_screen()==DECK_SCREEN_AMBIENT?"ambient":"deck",ViewNames[view],deck_model_button_count(),profile,page,context.can_go_back?"true":"false",link_subject&&lv_subject_get_int(link_subject)==1?"true":"false",weather_shown);
    return n>0&&n<static_cast<int>(size)?0:-1;
}
extern "C" void ui_set_firmware_version(const char *version) {
    if(version)snprintf(firmware_version,sizeof(firmware_version),"%s",version);
}
extern "C" void ui_boot_start(void) {
    if(!screen||boot)return;
    boot=lv_obj_create(nullptr);flat(boot,Bg);
    const int margin=sc(BootMargin),w=static_cast<int>(std::lround(616*scale)),h=static_cast<int>(std::lround(120*scale));
    auto *logo=clear_box(boot,(W-w)/2-margin,(H-h)/2-sc(4)-margin,w+2*margin,h+2*margin);
    lv_obj_add_event_cb(logo,boot_draw,LV_EVENT_DRAW_MAIN,nullptr);
    if(isdigit(static_cast<unsigned char>(firmware_version[0]))) {  /* "unknown" is not worth a line */
        char text[40];snprintf(text,sizeof(text),"v%s",firmware_version);
        boot_version=label(boot,text,0,0,W,&fq_font_dejavu_16,Bg);lv_obj_set_style_text_align(boot_version,LV_TEXT_ALIGN_CENTER,0);
        lv_obj_set_y(boot_version,H-sc(32)-ascent(boot_version));
    }
    lv_screen_load(boot);
    lv_anim_t anim;lv_anim_init(&anim);lv_anim_set_var(&anim,logo);lv_anim_set_exec_cb(&anim,boot_frame);
    lv_anim_set_values(&anim,0,BootEndMs);lv_anim_set_duration(&anim,BootEndMs);lv_anim_set_completed_cb(&anim,boot_done);
    lv_anim_start(&anim);
}
/* Shows one of the four screens (keys, agents, mixer, status); used by the tests. */
extern "C" void ui_show_view(int index) {if(screen)set_view(index);}
