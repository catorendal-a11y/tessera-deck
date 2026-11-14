// Tessera cockpit UI: a rail of four screens (keys, agents, mixer, status) beside the content.
#include "ui.h"
#include "icon_pack.h"
#include "deck_images.h"
#include "deck_model.h"
#include "time_service.h"
#include "ui_palette.h"
#include <Arduino.h>
#include <cctype>
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
constexpr int W=1024,H=600,Rail=84,Pad=26,Top=22,ContentW=W-Rail-2*Pad,HeadH=50,RailTop=84,RailPitch=60;
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
int view=ViewKeys,link_shown=-1;

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

constexpr int FaderW=163,FaderGap=18,TrackH=340,TrackW=110;
lv_obj_t *mixer_area=nullptr,*fader_zone[DECK_FADERS_MAX]{},*fader_fill[DECK_FADERS_MAX]{},*fader_knob[DECK_FADERS_MAX]{};
lv_obj_t *fader_value[DECK_FADERS_MAX]{},*fader_mute[DECK_FADERS_MAX]{},*fader_icon[DECK_FADERS_MAX]{};
deck_fader_t faders[DECK_FADERS_MAX]{};
int fader_count=0;
uint32_t fader_hold[DECK_FADERS_MAX]{},fader_sent[DECK_FADERS_MAX]{},faders_version=0;

constexpr int StatW=211,StatH=156,StatGap=14;
lv_obj_t *stats_area=nullptr,*stats_summary=nullptr,*stat_card[DECK_STATS_MAX]{},*stat_value[DECK_STATS_MAX]{};
lv_obj_t *stat_unit[DECK_STATS_MAX]{},*stat_fill[DECK_STATS_MAX]{},*stat_name[DECK_STATS_MAX]{};
int stat_count=-1;
uint32_t stats_version=0;

void flat(lv_obj_t *object,uint32_t color) {
    lv_obj_set_style_bg_color(object,lv_color_hex(color),0);
    lv_obj_set_style_bg_opa(object,LV_OPA_COVER,0);
    lv_obj_set_style_border_width(object,0,0);lv_obj_set_style_pad_all(object,0,0);
    lv_obj_set_style_shadow_width(object,0,0);lv_obj_set_scrollable(object,false);
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
    if(!(hold?deck_model_record_hold(ids[slot]):deck_model_record_press(ids[slot])))return;
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
    auto *tile=keys[slot];const int size=LV_MIN(lv_obj_get_width(tile),lv_obj_get_height(tile))-28;
    auto *arc=confirm_ring=lv_arc_create(tile);lv_obj_set_size(arc,size,size);lv_obj_center(arc);
    lv_arc_set_rotation(arc,270);lv_arc_set_bg_angles(arc,0,360);lv_arc_set_range(arc,0,100);lv_arc_set_value(arc,0);
    lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
    lv_obj_set_style_arc_width(arc,8,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,8,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc,lv_color_hex(Bg),LV_PART_MAIN);lv_obj_set_style_arc_color(arc,lv_color_hex(Accent),LV_PART_INDICATOR);
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
char asked_images[DECK_MAX_BUTTONS][64]{};uint32_t asked_layout=0,asked_at=0;
bool ask_once(const char *icon) {  /* each rebuild while images stream in would ask again and crowd out touches */
    if(asked_layout!=deck_model_buttons_version()||millis()-asked_at>60000){memset(asked_images,0,sizeof(asked_images));asked_layout=deck_model_buttons_version();asked_at=millis();}
    for(auto& asked:asked_images){if(!strncmp(asked,icon,sizeof(asked_images[0])-1))return false;if(!asked[0]){snprintf(asked,sizeof(asked_images[0]),"%s",icon);return true;}}
    return false;
}
/* The editor's Text size and Bold. There is no bold 16 px font, so bold at 16 uses bold 20. */
const lv_font_t *title_font(const deck_button_t& value) {
    switch(value.title_size) {
      case 20:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_20;
      case 24:return value.title_bold?&fq_font_dejavu_bold_24:&fq_font_dejavu_24;
      case 28:return value.title_bold?&fq_font_dejavu_bold_28:&fq_font_dejavu_28;
      default:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_16;
    }
}
/* The ring's inside is about 88 px wide: longer values ("3.8GHz", "302rpm") step down a size instead of spilling over. */
const lv_font_t *gauge_font(const char *text) {
    size_t n=strlen(text);
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
    if(button_version!=deck_model_buttons_version())for(int id=0;id<=DECK_MAX_BUTTONS;++id)if(awaiting[id]){stale[id]=true;awaiting[id]=false;}
    image_missing=false;image_generation=deck_image_generation();
    memset(name_label,0,sizeof(name_label));memset(glyph_label,0,sizeof(glyph_label));memset(value_label,0,sizeof(value_label));
    memset(sub_label,0,sizeof(sub_label));memset(bar_fill,0,sizeof(bar_fill));memset(ring_arc,0,sizeof(ring_arc));memset(gauge,0,sizeof(gauge));
    confirm_ring=nullptr;confirm_slot=-1;  /* the clean below deletes a ring in progress */
    lv_obj_clean(keys_area);for(auto& image:images){lv_image_cache_drop(&image.descriptor);image=ImageTile{};}
    memset(keys,0,sizeof(keys));memset(ids,0,sizeof(ids));memset(flash_until,0,sizeof(flash_until));
    constexpr int KeyW=138,KeyH=160,Gap=12;
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
        flat(tile,base_bg[slot]);lv_obj_set_style_radius(tile,20,0);
        if(value.style&DECK_STYLE_BORDER){lv_obj_set_style_border_width(tile,2,0);lv_obj_set_style_border_color(tile,lv_color_hex(value.border),0);}
        lv_obj_set_style_bg_color(tile,lv_color_hex(PressedBg),LV_STATE_PRESSED);
        lv_obj_set_style_transform_width(tile,-4,LV_STATE_PRESSED);lv_obj_set_style_transform_height(tile,-4,LV_STATE_PRESSED);  /* sinks under the finger */
        const bool title_top=cells==1&&value.title_position==1;  /* the icon moves down to make room for the title */
        const int cx=cells>1?58:KeyW/2,cy=cells>1?KeyH/2-12:title_top?KeyH-60:60;
        auto image=deck_image_get(value.icon);
        if(!image&&!strncmp(value.icon,"im:",3)){
            image_missing=true;
            /* The host may believe the panel still has it (the cache dropped it): ask for it again. */
            if(ask_once(value.icon)){char line[96];snprintf(line,sizeof(line),"{\"type\":\"image\",\"id\":\"%.60s\"}",value.icon);deck_model_queue_line(line);}
        }
        if(cells>1&&value.ring&&value.has_progress){
            /* A ring (a timer) on the left, the time big to its right. */
            auto *arc=ring_arc[slot]=lv_arc_create(tile);lv_obj_set_size(arc,104,104);lv_obj_set_pos(arc,14,(KeyH-104)/2);
            lv_arc_set_rotation(arc,270);lv_arc_set_bg_angles(arc,0,360);lv_arc_set_range(arc,0,100);lv_arc_set_value(arc,value.progress);
            lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
            lv_obj_set_style_arc_width(arc,10,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,10,LV_PART_INDICATOR);
            lv_obj_set_style_arc_color(arc,lv_color_hex(0x0A0E10),LV_PART_MAIN);lv_obj_set_style_arc_color(arc,lv_color_hex(value.color),LV_PART_INDICATOR);
        } else if(value.has_gauge){
            /* A ring filled to the percentage with the value inside; the badge says what is measured. */
            auto *arc=ring_arc[slot]=lv_arc_create(tile);lv_obj_set_size(arc,104,104);lv_obj_set_pos(arc,cx-52,cy-52);
            lv_arc_set_rotation(arc,270);lv_arc_set_bg_angles(arc,0,360);lv_arc_set_range(arc,0,100);lv_arc_set_value(arc,value.gauge_percent);
            lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
            lv_obj_set_style_arc_width(arc,8,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,8,LV_PART_INDICATOR);
            lv_obj_set_style_arc_color(arc,lv_color_hex(0x0A0E10),LV_PART_MAIN);lv_obj_set_style_arc_color(arc,lv_color_hex(value.color),LV_PART_INDICATOR);
            gauge[slot]=true;
            auto *shown=value_label[slot]=label(tile,value.gauge_text,cx-KeyW/2,cy-18,KeyW,&fq_font_dejavu_bold_28,value.color);
            gauge_value(shown,value.gauge_text);
            lv_obj_set_style_text_align(shown,LV_TEXT_ALIGN_CENTER,0);
            if(value.gauge_badge[0])glyph(tile,value.gauge_badge,18,18,20,Muted);
        } else if(image){
            auto& target=images[slot];target.image=image;target.widget=lv_image_create(tile);
            lv_obj_set_pos(target.widget,cx-image->width/2,cy-image->height/2);lv_obj_set_clickable(target.widget,false);
            image_frame(target);
        } else if(!(glyph_label[slot]=glyph(tile,value.icon,cx,cy,60,value.color))){
            auto *symbol=glyph_label[slot]=label(tile,fallback_icon(value.icon),0,cy-26,KeyW,&lv_font_montserrat_48,value.color);
            lv_obj_set_style_text_align(symbol,LV_TEXT_ALIGN_CENTER,0);
        }
        const uint32_t ink=(value.style&DECK_STYLE_TEXT)?value.text:Text;
        if(cells>1){
            /* Wide key: the title and a second line to the right of the icon, a progress bar underneath. */
            const int left=value.ring?130:112,room=width-left-14;
            name_label[slot]=label(tile,value.label,left,value.ring?40:30,room,value.ring?&fq_font_dejavu_bold_28:&fq_font_dejavu_bold_24,ink);
            sub_label[slot]=label(tile,value.sub,left,value.ring?82:70,room,&fq_font_dejavu_20,Muted);
            if(value.has_progress&&!value.ring){
                bar_width[slot]=room;
                auto *track=box(tile,left,KeyH-38,room,6,3,Bg);
                bar_fill[slot]=box(track,0,0,room*value.progress/100,6,3,value.color);
            }
        } else {
        /* Text size, position and bold from the editor: bottom (the default), top, middle or hidden. */
        const lv_font_t *font=title_font(value);const int px=lv_font_get_line_height(font);
        const int y=value.title_position==1?10:value.title_position==2?(KeyH-px)/2:KeyH-px-17;
        auto *name=name_label[slot]=label(tile,value.label,4,y,KeyW-8,font,ink);
        lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(name,value.title_position==3);
        }
        /* Small marks in the corner say what else a key does: a ring for a long press, two dots for a double tap. */
        int right=width-12;
        if(value.has_double)for(int dot=0;dot<2;++dot){box(tile,right-8,12,8,8,4,Muted);right-=13;}
        if(value.has_hold){auto *ring=box(tile,right-14,9,14,14,7,Card);lv_obj_set_style_bg_opa(ring,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(ring,2,0);lv_obj_set_style_border_color(ring,lv_color_hex(Muted),0);}
        if(value.confirm){for(auto code:{LV_EVENT_PRESSED,LV_EVENT_RELEASED,LV_EVENT_PRESS_LOST})lv_obj_add_event_cb(tile,confirm_touch,code,slot_data(slot));continue;}
        /* With a hold action, a click is a short press only; a long press reports a hold instead. */
        lv_obj_add_event_cb(tile,press,value.has_hold?LV_EVENT_SHORT_CLICKED:LV_EVENT_CLICKED,slot_data(slot));
        if(value.has_hold)lv_obj_add_event_cb(tile,press,LV_EVENT_LONG_PRESSED,slot_data(slot));
    }
    /* Empty slots stay visible as faint tiles, so the deck keeps its shape. */
    for(int slot=0;slot<DECK_MAX_BUTTONS;++slot)if(!keys[slot]&&!covered[slot])box(keys_area,(slot%6)*(KeyW+Gap),(slot/6)*(KeyH+Gap),KeyW,KeyH,20,0x0D1316);
    button_version=deck_model_buttons_version();live_version=deck_model_live_version();
}
/* Labels, colors and gauge values change in place: a rebuild would drop a touch in progress. */
void update_live() {
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
    live_version=deck_model_live_version();
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
    lv_obj_set_pos(button,x,25);lv_obj_set_size(button,132,96);lv_obj_set_style_radius(button,18,0);
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
    lv_obj_clean(agents_area);
    deck_agent_t list[DECK_AGENTS_MAX];int waiting=0;
    const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    for(int i=0;i<count;++i) {
        const auto& agent=lane_shown[i]=list[i];
        const uint32_t color=agent.state==DECK_AGENT_WAITING?Amber:agent.state==DECK_AGENT_WORKING?Cyan:Line;
        if(agent.state==DECK_AGENT_WAITING)++waiting;
        auto *lane=box(agents_area,0,i*160,ContentW,146,20,Card);lv_obj_set_style_clip_corner(lane,true,0);
        box(lane,0,0,7,146,0,color);
        const bool asks=agent.state==DECK_AGENT_WAITING&&agent.asks;  /* only a real question gets Allow and Deny */
        const int buttons=asks||agent.state==DECK_AGENT_WORKING?2:1,text_w=ContentW-26-buttons*132-(buttons-1)*12-38;
        const int name_y=agent.state==DECK_AGENT_WAITING?16:24;
        glyph(lane,agent_icon(agent.id),42,name_y+17,30,agent.state==DECK_AGENT_IDLE?Muted:color);
        auto *name=label(lane,agent.name,66,name_y,LV_SIZE_CONTENT,&fq_font_dejavu_bold_28,Text);
        lv_obj_update_layout(name);
        char state[40];
        snprintf(state,sizeof(state),"%s%s%s",agent.state==DECK_AGENT_WAITING?"waiting for you":agent.state==DECK_AGENT_WORKING?"working":"idle",
                 agent.at[0]&&agent.state!=DECK_AGENT_IDLE?" since ":"",agent.state!=DECK_AGENT_IDLE?agent.at:"");
        label(lane,state,66+lv_obj_get_width(name)+14,name_y+9,LV_SIZE_CONTENT,&fq_font_dejavu_20,agent.state==DECK_AGENT_IDLE?Muted:color);
        bool fits=true;
        if(agent.state==DECK_AGENT_WAITING){
            /* A question is shown in full: nobody should allow what they cannot read. Three lines at 20 px, else
               smaller type; a question that still does not fit gets Deny only, and Claude asks in its own dialog. */
            auto *asked=label(lane,agent.text,26,62,text_w,&fq_font_dejavu_20,Soft);
            lv_label_set_long_mode(asked,LV_LABEL_LONG_WRAP);lv_obj_set_height(asked,LV_SIZE_CONTENT);lv_obj_update_layout(asked);
            if(lv_obj_get_height(asked)>76){lv_obj_set_style_text_font(asked,&fq_font_dejavu_16,0);lv_obj_update_layout(asked);}
            fits=lv_obj_get_height(asked)<=80;lv_obj_set_height(asked,80);
        } else {
            label(lane,agent.text[0]?agent.text:agent.state==DECK_AGENT_IDLE?"Ready":"Working",26,68,text_w,&fq_font_dejavu_20,agent.state==DECK_AGENT_IDLE?Dim:Soft);
            if(agent.sub[0]){  /* the project, behind a folder */
                glyph(lane,"lc:e0d7",36,113,18,Dim);
                label(lane,agent.sub,54,102,text_w-28,&fq_font_dejavu_20,Dim);
            }
        }
        const int right=ContentW-20-132;
        if(asks){agent_button(lane,"Deny",right-144,2,i,1);if(fits)agent_button(lane,"Allow",right,0,i,0);}
        else if(agent.state==DECK_AGENT_WAITING)agent_button(lane,"Open",right,1,i,3);  /* waiting in its own window: bring it forward */
        else if(agent.state==DECK_AGENT_WORKING){agent_button(lane,"Open",right-144,1,i,3);agent_button(lane,"Stop",right,2,i,2);}
        else agent_button(lane,"Open",right,1,i,3);
    }
    if(!count){
        glyph(agents_area,"lc:e1bb",ContentW/2,130,72,Line);
        auto *empty=label(agents_area,"No agents are running",0,190,ContentW,&fq_font_dejavu_bold_24,Muted);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);
        auto *hint=label(agents_area,"Claude Code, Codex and ZCode show up here when they start",0,230,ContentW,&fq_font_dejavu_20,Dim);
        lv_obj_set_style_text_align(hint,LV_TEXT_ALIGN_CENTER,0);
    }
    char summary[32];
    if(waiting>1)snprintf(summary,sizeof(summary),"%d need you",waiting);
    else snprintf(summary,sizeof(summary),"%s",waiting?"One needs you":"Nobody is waiting");
    lv_label_set_text(agents_summary,summary);
    lv_obj_set_style_text_color(agents_summary,lv_color_hex(waiting?Amber:Muted),0);
    agents_version=agents_dot=deck_model_agents_version();agents_dirty=false;update_rail_dot();
}

/* ---- Mixer --------------------------------------------------------------------------------------- */
void draw_fader(int i) {
    const auto& fader=faders[i];
    const int fill=TrackH*fader.level/100;
    lv_obj_set_pos(fader_fill[i],44,TrackH-fill);lv_obj_set_height(fader_fill[i],fill);
    lv_obj_set_hidden(fader_fill[i],fill<4);
    set_color(fader_fill[i],LV_STYLE_BG_COLOR,fader.muted?Line:fader.color);
    lv_obj_set_y(fader_knob[i],LV_CLAMP(0,TrackH-fill-22,TrackH-44));
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
        auto *card=box(mixer_area,i*(FaderW+FaderGap),0,FaderW,H-2*Top,20,Card);
        fader_value[i]=label(card,"",0,18,FaderW,&fq_font_dejavu_bold_24,Text);lv_obj_set_style_text_align(fader_value[i],LV_TEXT_ALIGN_CENTER,0);
        auto *zone=fader_zone[i]=clear_box(card,(FaderW-TrackW)/2,64,TrackW,TrackH);lv_obj_set_clickable(zone,true);
        box(zone,44,0,22,TrackH,11,Bg);
        fader_fill[i]=box(zone,44,0,22,TrackH,11,faders[i].color);
        fader_knob[i]=box(zone,17,0,76,44,12,Text);
        for(auto code:{LV_EVENT_PRESSED,LV_EVENT_PRESSING,LV_EVENT_RELEASED})lv_obj_add_event_cb(zone,fader_touch,code,slot_data(i));
        auto *name=label(card,faders[i].name,4,424,FaderW-8,&fq_font_dejavu_20,Soft);lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);
        auto *mute=fader_mute[i]=lv_button_create(card);flat(mute,Card);
        lv_obj_set_pos(mute,(FaderW-80)/2,460);lv_obj_set_size(mute,80,80);lv_obj_set_style_radius(mute,40,0);
        lv_obj_set_style_border_width(mute,2,0);
        fader_icon[i]=glyph(mute,faders[i].mic?"lc:e118":"lc:e1ab",38,38,32,Muted);
        lv_obj_add_event_cb(mute,mute_pressed,LV_EVENT_CLICKED,slot_data(i));
        draw_fader(i);
    }
    if(!fader_count){auto *empty=label(mixer_area,"The PC has not sent its sound yet",0,240,ContentW,&fq_font_dejavu_20,Dim);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);}
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
    const int fill=(StatW-40)*stat.percent/100;
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
            auto *card=stat_card[i]=box(stats_area,(i%4)*(StatW+StatGap),(i/4)*(StatH+StatGap),StatW,StatH,20,Card);
            stat_name[i]=label(card,"",20,18,StatW-40,&fq_font_dejavu_20,Muted);
            auto *row=clear_box(card,20,44,StatW-40,62);
            lv_obj_set_flex_flow(row,LV_FLEX_FLOW_ROW);lv_obj_set_flex_align(row,LV_FLEX_ALIGN_START,LV_FLEX_ALIGN_END,LV_FLEX_ALIGN_CENTER);
            lv_obj_set_style_pad_column(row,6,0);
            stat_value[i]=lv_label_create(row);lv_label_set_text(stat_value[i],"");lv_obj_set_style_text_font(stat_value[i],&lv_font_montserrat_48,0);
            stat_unit[i]=lv_label_create(row);lv_label_set_text(stat_unit[i],"");lv_obj_set_style_text_font(stat_unit[i],&fq_font_dejavu_16,0);
            lv_obj_set_style_pad_bottom(stat_unit[i],9,0);
            auto *track=box(card,20,StatH-28,StatW-40,6,3,Bg);
            stat_fill[i]=box(track,0,0,0,6,3,Accent);
        }
        if(!count){auto *empty=label(stats_area,"The PC has not sent its readings yet",0,120,ContentW,&fq_font_dejavu_20,Dim);lv_obj_set_style_text_align(empty,LV_TEXT_ALIGN_CENTER,0);}
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
    if(rail_marker){lv_obj_set_hidden(rail_marker,active<0);if(active>=0)lv_obj_set_y(rail_marker,RailTop+active*RailPitch+9);}
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
    rail_marker=box(rail_items,0,RailTop+9,4,36,2,Accent);
    for(int i=0;i<count;++i) {
        auto *button=rail_btn[i]=lv_button_create(rail_items);flat(button,RailOn);
        lv_obj_set_pos(button,15,RailTop+i*RailPitch);lv_obj_set_size(button,54,54);lv_obj_set_style_radius(button,16,0);
        const char *icon=rail_list[i].kind<4?ViewIcons[rail_list[i].kind]:rail_list[i].icon;
        rail_gl[i]=glyph(button,icon,27,27,28,Dim);
        if(!rail_gl[i])rail_gl[i]=glyph(button,ViewIcons[0],27,27,28,Dim);
        lv_obj_add_event_cb(button,rail_pressed,LV_EVENT_CLICKED,slot_data(i));
        if(rail_list[i].kind==ViewAgents)rail_agents=i;
    }
    rail_dot=rail_agents>=0?box(rail_items,15+54-13,RailTop+rail_agents*RailPitch+3,12,12,6,Amber):nullptr;
    refresh_rail();
}
lv_obj_t *offline_card[3]{};
void show_offline(bool linked) {
    lv_obj_t *areas[3]={agents_area,mixer_area,stats_area};
    for(int i=0;i<3;++i) {
        if(!areas[i])continue;
        if(!offline_card[i]) {
            auto *card=offline_card[i]=box(lv_obj_get_parent(areas[i]),Pad+(ContentW-600)/2,H/2-80,600,150,22,WarnBg);
            lv_obj_set_style_border_width(card,2,0);lv_obj_set_style_border_color(card,lv_color_hex(Amber),0);
            auto *title=label(card,"PC not connected",0,34,600,&fq_font_dejavu_bold_28,Amber);lv_obj_set_style_text_align(title,LV_TEXT_ALIGN_CENTER,0);
            auto *hint=label(card,"Start Tessera on the PC, or check the USB cable",0,86,600,&fq_font_dejavu_20,Soft);lv_obj_set_style_text_align(hint,LV_TEXT_ALIGN_CENTER,0);
        }
        lv_obj_set_hidden(offline_card[i],linked);lv_obj_move_foreground(offline_card[i]);
    }
}
/* ---- About sheet: a long press on the logo shows the firmware, the PC link and a brightness slider. ---- */
lv_obj_t *about=nullptr,*about_link=nullptr,*about_level=nullptr;
void close_about() {if(about)lv_obj_delete(about);about=about_link=about_level=nullptr;}
void show_about_link() {
    if(!about_link)return;
    const bool linked=deck_model_host_linked(HostTimeoutMs);
    lv_label_set_text(about_link,linked?"PC connected":"PC not connected");set_color(about_link,LV_STYLE_TEXT_COLOR,linked?Accent:Amber);
}
void about_tapped(lv_event_t *event) {if(lv_event_get_target(event)==about)close_about();}  /* outside the card */
void brightness_moved(lv_event_t *event) {
    auto *slider=static_cast<lv_obj_t*>(lv_event_get_target(event));const int level=lv_slider_get_value(slider);
    /* Every step lights the panel; the level is saved (and the host told) once, when the finger lifts. */
    deck_model_request_brightness(level,lv_event_get_code(event)==LV_EVENT_RELEASED);
    lv_label_set_text_fmt(about_level,"%d %%",level);
}
void open_about(lv_event_t *) {
    if(about||deck_model_locked())return;
    about=lv_obj_create(screen);flat(about,Bg);lv_obj_set_style_bg_opa(about,LV_OPA_70,0);lv_obj_set_pos(about,0,0);lv_obj_set_size(about,W,H);
    lv_obj_add_event_cb(about,about_tapped,LV_EVENT_CLICKED,nullptr);
    constexpr int CardW=460;
    auto *card=box(about,Rail+16,16,CardW,300,22,Card);lv_obj_set_clickable(card,true);
    lv_obj_set_style_border_width(card,2,0);lv_obj_set_style_border_color(card,lv_color_hex(Line),0);
    label(card,"Tessera",28,24,CardW-56,&fq_font_dejavu_bold_28,Text);
    char version[48];snprintf(version,sizeof(version),"Firmware %s",firmware_version);
    label(card,version,28,70,CardW-56,&fq_font_dejavu_20,Soft);
    about_link=label(card,"",28,102,CardW-56,&fq_font_dejavu_20,Accent);show_about_link();
    label(card,"Brightness",28,166,CardW-160,&fq_font_dejavu_20,Soft);
    about_level=label(card,"",CardW-128,166,100,&fq_font_dejavu_20,Text);lv_obj_set_style_text_align(about_level,LV_TEXT_ALIGN_RIGHT,0);
    auto *slider=lv_slider_create(card);lv_obj_set_pos(slider,40,224);lv_obj_set_size(slider,CardW-80,20);
    lv_slider_set_range(slider,1,100);lv_slider_set_value(slider,deck_model_brightness(),LV_ANIM_OFF);
    lv_obj_set_style_bg_color(slider,lv_color_hex(Line),LV_PART_MAIN);lv_obj_set_style_bg_color(slider,lv_color_hex(Accent),LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(slider,lv_color_hex(Text),LV_PART_KNOB);lv_obj_set_style_pad_all(slider,10,LV_PART_KNOB);
    lv_obj_set_ext_click_area(slider,20);  /* a fingertip, not a 20 px bar */
    lv_label_set_text_fmt(about_level,"%d %%",deck_model_brightness());
    for(auto code:{LV_EVENT_VALUE_CHANGED,LV_EVENT_RELEASED})lv_obj_add_event_cb(slider,brightness_moved,code,nullptr);
}

/* ---- Panel lock: the logo turns into a lock badge; holding it LockHoldMs unlocks and tells the host. ---- */
lv_obj_t *logo=nullptr,*lock_badge=nullptr,*lock_ring=nullptr;
int lock_shown=-1;uint32_t lock_pressed_at=0;
void lock_touched(lv_event_t *) {lock_pressed_at=millis();}
void update_lock() {
    const int locked=deck_model_locked()?1:0;
    if(locked!=lock_shown){
        lock_shown=locked;lv_obj_set_hidden(logo,locked);lv_obj_set_hidden(lock_badge,!locked);
        if(locked)close_about();
    }
    const bool holding=locked&&lv_obj_has_state(lock_badge,LV_STATE_PRESSED);
    const uint32_t held=holding?millis()-lock_pressed_at:0;
    lv_arc_set_value(lock_ring,static_cast<int32_t>(held>=LockHoldMs?100:held*100/LockHoldMs));
    if(held<LockHoldMs)return;
    deck_model_set_locked(false);deck_model_queue_line("{\"type\":\"unlocked\"}");
    for(auto *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_wait_release(indev);  /* the same touch must not tap what shows next */
}

void update_link() {
    const int linked=deck_model_host_linked(HostTimeoutMs)?1:0;
    if(linked==link_shown)return;
    link_shown=linked;lv_obj_set_hidden(link_label,linked);show_about_link();
    for(auto *area:{agents_area,mixer_area,stats_area})if(area)lv_obj_set_style_opa(area,linked?LV_OPA_COVER:LV_OPA_40,0);
    show_offline(linked);
    if(linked){agents_dirty=true;sync_stats();return;}
    for(auto *summary:{agents_summary,stats_summary}){lv_label_set_text(summary,"PC not connected");lv_obj_set_style_text_color(summary,lv_color_hex(Amber),0);}
}
/* Title on the left, a one-line summary on the right. */
lv_obj_t *head(lv_obj_t *parent,const char *title,lv_obj_t **summary) {
    auto *name=label(parent,title,Pad,Top-2,ContentW/2,&fq_font_dejavu_bold_28,Text);
    *summary=label(parent,"",Pad+ContentW/2,Top+6,ContentW/2,&fq_font_dejavu_20,Muted);
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
    constexpr int Tile=13,Space=3;
    for(int row=0;row<3;++row)for(int col=0;col<3;++col) {
        if(row==0&&col==2)continue;
        box(parent,x+col*(Tile+Space),y+4+row*(Tile+Space),Tile,Tile,4,sweep((row+col)/4.f));
    }
    box(parent,x+34,y,12,12,4,Amber);
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
    const int Dot=twelve?32:36,Pitch=twelve?37:42,Space=twelve?24:28,Gap=20;  /* Gap: digits to AM/PM */
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
                if(draw)box(ambient_clock,at,row*Pitch,Dot,Dot,7,vivid(sweep((index+col/5.f)/(glyphs>0?glyphs:1))));
                else{if(at<left)left=at;if(at+Dot>right)right=at+Dot;}
            }
            x+=columns*Pitch-(Pitch-Dot)+Space;
        }
    };
    tiles(0,false);
    const int shift=(W-(right-left)-suffix)/2-left;
    tiles(shift,true);
    lv_obj_set_pos(ambient_meridiem,right+shift+Gap,lv_obj_get_y(ambient_clock)+7*Pitch-(Pitch-Dot)-48);  /* on the digits' baseline */
}
void show_ambient(bool on) {
    if(!ambient||on==(deck_model_screen()==DECK_SCREEN_AMBIENT))return;
    deck_model_set_screen(on?DECK_SCREEN_AMBIENT:DECK_SCREEN_DECK);
    if(on){ambient_time[0]='\0';ambient_seen=0;}
    lv_screen_load(on?ambient:screen);
}
void ambient_touched(lv_event_t *) {
    if(deck_model_screen()!=DECK_SCREEN_AMBIENT)return;
    show_ambient(false);deck_model_note_touch_return();deck_model_request_wake();
}
void build_ambient() {
    ambient=lv_obj_create(nullptr);flat(ambient,Bg);
    ambient_clock=box(ambient,0,80,W,7*42,0,Bg);
    ambient_meridiem=label(ambient,"",0,0,LV_SIZE_CONTENT,&fq_font_dejavu_bold_40,Soft);
    ambient_date=label(ambient,"",0,404,W,&fq_font_dejavu_bold_40,Text);lv_obj_set_style_text_align(ambient_date,LV_TEXT_ALIGN_CENTER,0);
    /* The weather: an icon and the host's line side by side, centred together. */
    auto *row=clear_box(ambient,0,466,W,LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row,LV_FLEX_FLOW_ROW);lv_obj_set_flex_align(row,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(row,16,0);
    ambient_icon=label(row,"",0,0,60,&deck_lucide_60,Soft);lv_obj_set_style_text_align(ambient_icon,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(ambient_icon,true);
    ambient_line=label(row,"",0,0,LV_SIZE_CONTENT,&fq_font_dejavu_28,Soft);lv_obj_set_style_max_width(ambient_line,W-200,0);
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

int view_before_question=-1;  /* the screen a permission question took the panel away from */
bool question_waiting() {
    deck_agent_t list[DECK_AGENTS_MAX];const int count=deck_model_agents(list,DECK_AGENTS_MAX);
    for(int i=0;i<count;++i)if(list[i].state==DECK_AGENT_WAITING&&list[i].asks)return true;
    return false;
}
void update(lv_timer_t*) {
    /* Compare the insert generation, not the count: a full cache evicts one image per insert. */
    if(button_version!=deck_model_buttons_version()||(image_missing&&deck_image_generation()!=image_generation))build_keys();
    else if(live_version!=deck_model_live_version())update_live();
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
    /* Runs every 40 ms: only touch the label when the minute changed. */
    const char *clock_now=time_service_time_text();
    if(strcmp(lv_label_get_text(clock_label),clock_now))lv_label_set_text(clock_label,clock_now);
}
}

extern "C" void ui_init(void) {
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
    /* Status */
    head(views[ViewStatus],"This PC",&stats_summary);
    stats_area=clear_box(views[ViewStatus],Pad,Top+HeadH,ContentW,H-Top-HeadH);
    /* Rail */
    auto *rail=box(screen,0,0,Rail,H,0,RailBg);
    logo=clear_box(rail,0,8,Rail,68);make_logo(logo,19,12);lv_obj_set_clickable(logo,true);
    lv_obj_add_event_cb(logo,open_about,LV_EVENT_LONG_PRESSED,nullptr);
    lock_badge=lv_button_create(rail);flat(lock_badge,RailOn);lv_obj_set_pos(lock_badge,15,14);lv_obj_set_size(lock_badge,54,54);
    lv_obj_set_style_radius(lock_badge,27,0);lv_obj_add_event_cb(lock_badge,lock_touched,LV_EVENT_PRESSED,nullptr);
    if(!glyph(lock_badge,"lc:e10b",27,27,26,Amber)){auto *mark=label(lock_badge,"L",0,15,54,&fq_font_dejavu_bold_20,Amber);lv_obj_set_style_text_align(mark,LV_TEXT_ALIGN_CENTER,0);}
    lock_ring=lv_arc_create(lock_badge);lv_obj_set_size(lock_ring,54,54);lv_obj_set_pos(lock_ring,0,0);
    lv_arc_set_rotation(lock_ring,270);lv_arc_set_bg_angles(lock_ring,0,360);lv_arc_set_range(lock_ring,0,100);lv_arc_set_value(lock_ring,0);
    lv_obj_remove_style(lock_ring,nullptr,LV_PART_KNOB);lv_obj_set_clickable(lock_ring,false);
    lv_obj_set_style_arc_width(lock_ring,3,LV_PART_MAIN);lv_obj_set_style_arc_width(lock_ring,3,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(lock_ring,lv_color_hex(Amber),LV_PART_MAIN);lv_obj_set_style_arc_color(lock_ring,lv_color_hex(Accent),LV_PART_INDICATOR);
    lv_obj_set_hidden(lock_badge,true);
    rail_items=clear_box(rail,0,0,Rail,H);
    link_label=label(rail,"NO PC",0,H-74,Rail,&fq_font_dejavu_bold_20,Amber);lv_obj_set_style_text_align(link_label,LV_TEXT_ALIGN_CENTER,0);
    clock_label=label(rail,"--:--",0,H-44,Rail,&fq_font_dejavu_20,Soft);lv_obj_set_style_text_align(clock_label,LV_TEXT_ALIGN_CENTER,0);
    for(lv_indev_t *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_add_event_cb(indev,wake_touch,LV_EVENT_PRESSED,nullptr);
    build_ambient();
    build_keys();build_rail();update_context();build_agents();sync_faders();sync_stats();set_view(ViewKeys);link_shown=-1;update_link();
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
                         deck_model_screen()==DECK_SCREEN_AMBIENT?"ambient":"deck",ViewNames[view],deck_model_button_count(),profile,page,context.can_go_back?"true":"false",link_shown==1?"true":"false",weather_shown);
    return n>0&&n<static_cast<int>(size)?0:-1;
}
extern "C" void ui_set_firmware_version(const char *version) {
    if(version)snprintf(firmware_version,sizeof(firmware_version),"%s",version);
}
/* Shows one of the four screens (keys, agents, mixer, status); used by the tests. */
extern "C" void ui_show_view(int index) {if(screen)set_view(index);}
