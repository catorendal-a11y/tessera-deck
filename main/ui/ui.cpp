// Standalone full-screen Tessera UI.
#include "ui.h"
#include "icon_pack.h"
#include "deck_images.h"
#include "deck_model.h"
#include "time_service.h"
#include <Arduino.h>
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

namespace {
constexpr int W=1024,H=600,Header=76,Cell=150,Gap=17,X=19,Y=17;
constexpr uint32_t Bg=0x091014,HeaderBg=0x101A1F,Surface=0x172329;
constexpr uint32_t Border=0x31444D,Text=0xE8F4EF,Muted=0x78909A,Accent=0x58E09B;
constexpr uint32_t PressedBg=0x254E3B,OkBg=0x1E6042,AlertBg=0x6E2633,Amber=0xFFB74D;
/* The four logo tile colors; they are the interface roles: go, info, media, toggle. */
constexpr uint32_t Cyan=0x4DD0E1,Purple=0xB388FF;
uint32_t mix(uint32_t from,uint32_t to,float t);
/* The host pings every second; three missed pings mean nobody runs the keys. */
constexpr int64_t HostTimeoutMs=3500;
/* A pressed key stays highlighted until the host confirms it. Long multi-step
 * actions confirm late, so the highlight only gives up after this long. */
constexpr uint32_t PendingMs=10000;
lv_obj_t *screen=nullptr,*grid=nullptr,*profile_label=nullptr,*page_label=nullptr,*clock_label=nullptr;
lv_obj_t *link_pill=nullptr,*link_dot=nullptr,*link_label=nullptr;
int link_shown=-1;
lv_obj_t *keys[DECK_MAX_BUTTONS]{};
int ids[DECK_MAX_BUTTONS]{};
uint32_t button_version=0,live_version=0,context_version=0;
lv_obj_t *gauge_arc[DECK_MAX_BUTTONS]{},*gauge_value[DECK_MAX_BUTTONS]{};
lv_obj_t *name_label[DECK_MAX_BUTTONS]{},*glyph_label[DECK_MAX_BUTTONS]{};
uint32_t flash_until[DECK_MAX_BUTTONS]{};

struct ImageTile {
    std::shared_ptr<const DeckImage> image;
    lv_obj_t *widget=nullptr;
    lv_image_dsc_t descriptor{};
    uint32_t due=0;
    size_t frame=0;
};
ImageTile images[DECK_MAX_BUTTONS];

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
    return result;
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
const lv_font_t *title_font(const deck_button_t& value) {
    switch(value.title_size) {
      case 20:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_20;
      case 24:return value.title_bold?&fq_font_dejavu_bold_24:&fq_font_dejavu_24;
      case 28:return value.title_bold?&fq_font_dejavu_bold_28:&fq_font_dejavu_28;
      default:return value.title_bold?&fq_font_dejavu_bold_20:&fq_font_dejavu_16;
    }
}
void image_frame(ImageTile& value) {
    value.descriptor.header.magic=LV_IMAGE_HEADER_MAGIC;value.descriptor.header.cf=LV_COLOR_FORMAT_ARGB8888;
    value.descriptor.header.w=value.image->width;value.descriptor.header.h=value.image->height;
    value.descriptor.header.stride=value.image->width*4;value.descriptor.data=value.image->frames[value.frame].data();
    value.descriptor.data_size=value.image->frames[value.frame].size();lv_image_cache_drop(&value.descriptor);
    lv_image_set_src(value.widget,&value.descriptor);lv_obj_invalidate(value.widget);
    value.due=millis()+value.image->durations[value.frame];
}
uint32_t base_bg[DECK_MAX_BUTTONS],base_top[DECK_MAX_BUTTONS],base_bottom[DECK_MAX_BUTTONS];  /* resting key fill, restored after a flash */
void fill(int slot,uint32_t top,uint32_t bottom) {
    lv_obj_set_style_bg_color(keys[slot],lv_color_hex(top),0);lv_obj_set_style_bg_grad_color(keys[slot],lv_color_hex(bottom),0);
    lv_obj_set_style_bg_grad_dir(keys[slot],LV_GRAD_DIR_VER,0);
}
void flash(int slot,uint32_t color,uint32_t ms) {
    fill(slot,color,mix(color,0x000000,.25f));flash_until[slot]=millis()+ms;
}
void press(lv_event_t *event) {
    const int slot=static_cast<int>(reinterpret_cast<intptr_t>(lv_event_get_user_data(event)));
    if(slot<0||slot>=DECK_MAX_BUTTONS||!ids[slot])return;
    const bool long_press=lv_event_get_code(event)==LV_EVENT_LONG_PRESSED;
    if(!(long_press?deck_model_record_hold(ids[slot]):deck_model_record_press(ids[slot])))return;
    /* Without a host nothing runs the action: say so at once instead of
     * flashing as if it worked. */
    if(deck_model_host_linked(HostTimeoutMs))flash(slot,PressedBg,PendingMs);
    else flash(slot,AlertBg,500);
}
/* A touch on a dimmed panel only wakes it, wherever it lands, and never
 * reaches a key: the indev ignores the rest of the touch until release. */
void wake_touch(lv_event_t *event) {
    if(!deck_model_dimmed())return;
    deck_model_request_wake();
    auto *indev=static_cast<lv_indev_t*>(lv_event_get_target(event));
    lv_indev_stop_processing(indev);lv_indev_wait_release(indev);
}
void update_link() {
    const int linked=deck_model_host_linked(HostTimeoutMs)?1:0;
    if(linked==link_shown)return;
    link_shown=linked;
    lv_obj_set_style_bg_color(link_pill,lv_color_hex(linked?0x16372A:0x3A2E1A),0);
    lv_obj_set_style_bg_color(link_dot,lv_color_hex(linked?Accent:Amber),0);
    lv_obj_set_style_text_color(link_label,lv_color_hex(linked?0xA8F2CA:0xFFD699),0);
    lv_label_set_text(link_label,linked?"PC CONNECTED":"NO PC");
}
void style_gauge(int slot,const deck_button_t& value) {
    if(!gauge_arc[slot]||!gauge_value[slot])return;
    lv_arc_set_value(gauge_arc[slot],value.gauge_percent);
    lv_obj_set_style_arc_color(gauge_arc[slot],lv_color_hex(value.color),LV_PART_INDICATOR);
    lv_label_set_text(gauge_value[slot],value.gauge_text);
    lv_obj_set_style_text_color(gauge_value[slot],lv_color_hex(value.color),0);
    lv_obj_set_style_text_font(gauge_value[slot],strlen(value.gauge_text)>3?&fq_font_dejavu_bold_24:&fq_font_dejavu_bold_28,0);
}
void make_gauge(int slot,lv_obj_t *tile,const deck_button_t& value) {
    constexpr int D=108,Top=6;
    auto *disc=lv_obj_create(tile);flat(disc,mix(base_bg[slot],0xFFFFFF,.035f));lv_obj_set_size(disc,D-36,D-36);
    lv_obj_set_pos(disc,(Cell-(D-36))/2,Top+18);lv_obj_set_style_radius(disc,LV_RADIUS_CIRCLE,0);lv_obj_remove_flag(disc,LV_OBJ_FLAG_CLICKABLE);
    auto *arc=lv_arc_create(tile);gauge_arc[slot]=arc;
    lv_obj_set_size(arc,D,D);lv_obj_set_pos(arc,(Cell-D)/2,Top);
    lv_arc_set_range(arc,0,100);lv_arc_set_bg_angles(arc,135,45);
    lv_obj_remove_style(arc,nullptr,LV_PART_KNOB);lv_obj_set_clickable(arc,false);
    lv_obj_set_style_arc_width(arc,13,LV_PART_MAIN);lv_obj_set_style_arc_width(arc,13,LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc,lv_color_hex(0x1E2B32),LV_PART_MAIN);
    lv_obj_set_style_arc_rounded(arc,true,LV_PART_MAIN);lv_obj_set_style_arc_rounded(arc,true,LV_PART_INDICATOR);
    gauge_value[slot]=label(tile,"",0,Top+D/2-16,Cell,&fq_font_dejavu_bold_28,Text);
    lv_obj_set_style_text_align(gauge_value[slot],LV_TEXT_ALIGN_CENTER,0);
    style_gauge(slot,value);
}
void update_live() {
    for(int n=0;n<deck_model_button_count();++n){deck_button_t item{};
        if(!deck_model_get_button(n,&item)||item.id<1||item.id>DECK_MAX_BUTTONS)continue;
        const int slot=item.id-1;
        if(item.has_gauge)style_gauge(slot,item);
        if(glyph_label[slot])lv_obj_set_style_text_color(glyph_label[slot],lv_color_hex(item.color),0);
        if(name_label[slot]&&strcmp(lv_label_get_text(name_label[slot]),item.label))lv_label_set_text(name_label[slot],item.label);}
    live_version=deck_model_live_version();
}
void rebuild() {
    memset(gauge_arc,0,sizeof(gauge_arc));memset(gauge_value,0,sizeof(gauge_value));memset(name_label,0,sizeof(name_label));memset(glyph_label,0,sizeof(glyph_label));
    lv_obj_clean(grid);for(auto& image:images){lv_image_cache_drop(&image.descriptor);image=ImageTile{};}
    memset(keys,0,sizeof(keys));memset(ids,0,sizeof(ids));memset(flash_until,0,sizeof(flash_until));
    for(int slot=0;slot<DECK_MAX_BUTTONS;++slot) {
        deck_button_t value{};bool assigned=false;
        for(int n=0;n<deck_model_button_count();++n){deck_button_t item{};if(deck_model_get_button(n,&item)&&item.id==slot+1){value=item;assigned=true;break;}}
        auto *tile=lv_button_create(grid);keys[slot]=tile;
        lv_obj_set_pos(tile,X+(slot%6)*(Cell+Gap),Y+(slot/6)*(Cell+Gap));lv_obj_set_size(tile,Cell,Cell);
        const uint32_t mid=assigned?((value.style&DECK_STYLE_BG)?value.bg:Surface):0x0E171B;
        base_bg[slot]=mid;base_top[slot]=mix(mid,0xFFFFFF,assigned?.05f:0.f);base_bottom[slot]=mix(mid,0x000000,assigned?.28f:0.f);
        flat(tile,mid);lv_obj_set_style_radius(tile,22,0);fill(slot,base_top[slot],base_bottom[slot]);
        const bool own_border=assigned&&(value.style&DECK_STYLE_BORDER);
        lv_obj_set_style_border_width(tile,own_border?3:1,0);
        lv_obj_set_style_border_color(tile,lv_color_hex(!assigned?0x1B2A30:own_border?value.border:mix(Border,value.color,.38f)),0);
        if(assigned){lv_obj_set_style_shadow_width(tile,18,0);lv_obj_set_style_shadow_color(tile,lv_color_hex(0x000000),0);lv_obj_set_style_shadow_opa(tile,LV_OPA_50,0);lv_obj_set_style_shadow_offset_y(tile,5,0);}
        lv_obj_set_style_bg_color(tile,lv_color_hex(0x244D3A),LV_STATE_PRESSED);
        if(!assigned){lv_obj_set_clickable(tile,false);auto *plus=label(tile,"+",0,51,Cell,&fq_font_dejavu_28,0x263940);lv_obj_set_style_text_align(plus,LV_TEXT_ALIGN_CENTER,0);continue;}
        ids[slot]=value.id;char packed[5]{};const bool lucide=deck_lucide_glyph(value.icon,packed);auto image=deck_image_get(value.icon);
        if(value.has_gauge){make_gauge(slot,tile,value);}
        else if(image){auto& target=images[slot];target.image=image;target.widget=lv_image_create(tile);lv_obj_set_pos(target.widget,(Cell-image->width)/2,value.title_position==1?57:18);image_frame(target);}
        else {auto *glyph=glyph_label[slot]=label(tile,lucide?packed:fallback_icon(value.icon),0,value.title_position==1?61:(lucide?17:25),Cell,lucide?&deck_lucide_60:&lv_font_montserrat_48,value.color);lv_obj_set_style_text_align(glyph,LV_TEXT_ALIGN_CENTER,0);}
        // Bold 16 uses the 20 px bold font; place it by that height, as the editor does.
        const int size=value.title_size?value.title_size:16,px=value.title_bold&&size==16?20:size;
        const int y=value.title_position==1?10:value.title_position==2?(Cell-px)/2:Cell-px-17;
        auto *name=name_label[slot]=label(tile,value.label,9,y,Cell-18,title_font(value),(value.style&DECK_STYLE_TEXT)?value.text:value.has_gauge?mix(Text,Muted,.3f):Text);lv_obj_set_style_text_align(name,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_hidden(name,value.title_position==3);
        /* With a hold action, a click is a short press only; a long press reports a hold instead. */
        lv_obj_add_event_cb(tile,press,value.has_hold?LV_EVENT_SHORT_CLICKED:LV_EVENT_CLICKED,reinterpret_cast<void*>(static_cast<intptr_t>(slot)));
        if(value.has_hold)lv_obj_add_event_cb(tile,press,LV_EVENT_LONG_PRESSED,reinterpret_cast<void*>(static_cast<intptr_t>(slot)));
    }
    button_version=deck_model_buttons_version();live_version=deck_model_live_version();
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
void upper_case(const char *in,char *out,size_t size) {
    size_t n=0;
    for(;*in&&n+1<size;++in,++n)out[n]=*in>='a'&&*in<='z'?static_cast<char>(*in-32):*in;
    out[n]='\0';
}
uint32_t mix(uint32_t from,uint32_t to,float t) {
    auto channel=[&](int shift){return static_cast<uint32_t>(((from>>shift)&0xFF)+(static_cast<int>((to>>shift)&0xFF)-static_cast<int>((from>>shift)&0xFF))*t+.5f)&0xFF;};
    return channel(16)<<16|channel(8)<<8|channel(0);
}
/* The brand gradient: mint -> cyan -> purple, t in 0..1. */
uint32_t sweep(float t) {return t<.5f?mix(Accent,Cyan,t*2):mix(Cyan,Purple,(t-.5f)*2);}
lv_obj_t *tile(lv_obj_t *parent,int x,int y,int size,int radius,uint32_t color) {
    auto *item=lv_obj_create(parent);flat(item,color);lv_obj_set_pos(item,x,y);lv_obj_set_size(item,size,size);lv_obj_set_style_radius(item,radius,0);
    return item;
}
/* The Tessera mark: a 3x3 mosaic on the brand gradient; the top-right tile has broken loose. */
void make_logo(lv_obj_t *parent,int x,int y) {
    constexpr int Tile=13,Space=3;
    for(int row=0;row<3;++row)for(int col=0;col<3;++col) {
        if(row==0&&col==2)continue;
        tile(parent,x+col*(Tile+Space),y+4+row*(Tile+Space),Tile,4,sweep((row+col)/4.f));
    }
    tile(parent,x+34,y,12,4,Amber);
}
/* ---- Ambient clock: a big clock built from brand-gradient tiles, the date and a host-supplied line. ---- */
lv_obj_t *ambient,*ambient_clock,*ambient_date,*ambient_line;
char ambient_time[8]="";uint32_t ambient_seen=0;
const char *const DigitGlyphs[11][7]={
    {"01110","10001","10011","10101","11001","10001","01110"},{"00100","01100","00100","00100","00100","00100","01110"},
    {"01110","10001","00001","00010","00100","01000","11111"},{"11110","00001","00001","01110","00001","00001","11110"},
    {"00010","00110","01010","10010","11111","00010","00010"},{"11111","10000","11110","00001","00001","10001","01110"},
    {"00110","01000","10000","11110","10001","10001","01110"},{"11111","00001","00010","00100","01000","01000","01000"},
    {"01110","10001","10001","01110","10001","10001","01110"},{"01110","10001","10001","01111","00001","00010","01100"},
    {"0","0","1","0","1","0","0"}};
void draw_big_clock(const char *text) {
    constexpr int Cell=26,Pitch=31,Gap=22;
    lv_obj_clean(ambient_clock);
    int width=0,glyphs=0;
    for(const char *c=text;*c;++c){width+=(*c==':'?1:5)*Pitch-(Pitch-Cell)+Gap;++glyphs;}
    width-=Gap;int x=(W-width)/2,index=0;
    for(const char *c=text;*c;++c,++index) {
        const int glyph=*c==':'?10:(*c>='0'&&*c<='9'?*c-'0':-1);
        const int columns=*c==':'?1:5;
        if(glyph>=0)for(int row=0;row<7;++row)for(int col=0;col<columns;++col)
            if(DigitGlyphs[glyph][row][col]=='1')tile(ambient_clock,x+col*Pitch,row*Pitch,Cell,5,sweep((index+col/5.f)/(glyphs>0?glyphs:1)));
        x+=columns*Pitch-(Pitch-Cell)+Gap;
    }
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
    ambient_clock=lv_obj_create(ambient);flat(ambient_clock,Bg);lv_obj_set_pos(ambient_clock,0,120);lv_obj_set_size(ambient_clock,W,7*31);
    lv_obj_clear_flag(ambient_clock,LV_OBJ_FLAG_CLICKABLE);
    ambient_date=label(ambient,"",0,360,W,&fq_font_dejavu_bold_28,Text);lv_obj_set_style_text_align(ambient_date,LV_TEXT_ALIGN_CENTER,0);
    ambient_line=label(ambient,"",60,420,W-120,&fq_font_dejavu_24,Muted);lv_obj_set_style_text_align(ambient_line,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_add_event_cb(ambient,ambient_touched,LV_EVENT_PRESSED,nullptr);
}
void update_ambient() {
    const int request=deck_model_take_screen_request();
    if(request==DECK_SCREEN_AMBIENT)show_ambient(true);else if(request==DECK_SCREEN_DECK)show_ambient(false);
    if(deck_model_screen()!=DECK_SCREEN_AMBIENT)return;
    const char *now=time_service_time_text();
    if(strcmp(now,ambient_time)){snprintf(ambient_time,sizeof(ambient_time),"%s",now);draw_big_clock(ambient_time);lv_label_set_text(ambient_date,time_service_date_text());}
    if(ambient_seen!=deck_model_ambient_version()){char line[DECK_AMBIENT_MAX+1];deck_model_ambient(line,sizeof(line));lv_label_set_text(ambient_line,line);ambient_seen=deck_model_ambient_version();}
}
void update_context() {
    const auto context=deck_model_context();
    char profile[64],name[64],page[80];
    upper_case(context.profile,profile,sizeof(profile));
    title_case(context.page,name,sizeof(name));
    snprintf(page,sizeof(page),"%s%s",context.can_go_back?"<  ":"",name);
    lv_label_set_text(profile_label,profile);lv_label_set_text(page_label,page);context_version=deck_model_context_version();
}
void update(lv_timer_t*) {
    if(button_version!=deck_model_buttons_version())rebuild();
    else if(live_version!=deck_model_live_version())update_live();
    if(context_version!=deck_model_context_version())update_context();
    for(auto& image:images)if(image.image&&image.image->frames.size()>1&&static_cast<int32_t>(millis()-image.due)>=0){image.frame=(image.frame+1)%image.image->frames.size();image_frame(image);}
    int id=0;deck_feedback_t result;
    while(deck_model_take_feedback(&id,&result))for(int i=0;i<DECK_MAX_BUTTONS;++i)if(ids[i]==id&&keys[i])flash(i,result==DECK_FEEDBACK_ALERT?AlertBg:OkBg,500);
    for(int i=0;i<DECK_MAX_BUTTONS;++i)if(flash_until[i]&&static_cast<int32_t>(millis()-flash_until[i])>=0){fill(i,base_top[i],base_bottom[i]);flash_until[i]=0;}
    update_link();
    update_ambient();
    lv_label_set_text(clock_label,time_service_time_text());
}
}

extern "C" void ui_show_destination(int) {if(screen){deck_model_set_screen(DECK_SCREEN_DECK);lv_screen_load(screen);}}
extern "C" void ui_init(void) {
    screen=lv_obj_create(nullptr);flat(screen,Bg);lv_obj_set_style_bg_grad_color(screen,lv_color_hex(0x05090B),0);lv_obj_set_style_bg_grad_dir(screen,LV_GRAD_DIR_VER,0);
    auto *header=lv_obj_create(screen);flat(header,mix(HeaderBg,0xFFFFFF,.05f));lv_obj_set_style_bg_grad_color(header,lv_color_hex(HeaderBg),0);lv_obj_set_style_bg_grad_dir(header,LV_GRAD_DIR_VER,0);
    lv_obj_set_size(header,W,Header);lv_obj_set_style_radius(header,0,0);
    make_logo(header,20,15);
    auto *wordmark=label(header,"TESSERA",80,26,220,&fq_font_dejavu_bold_24,Text);lv_obj_set_style_text_letter_space(wordmark,6,0);
    profile_label=label(header,"LOCAL",340,10,380,&fq_font_dejavu_16,Muted);lv_obj_set_style_text_align(profile_label,LV_TEXT_ALIGN_CENTER,0);lv_obj_set_style_text_letter_space(profile_label,2,0);
    page_label=label(header,"Main",340,29,380,&fq_font_dejavu_bold_28,Text);lv_obj_set_style_text_align(page_label,LV_TEXT_ALIGN_CENTER,0);
    link_pill=lv_obj_create(header);flat(link_pill,0x16372A);lv_obj_set_pos(link_pill,730,21);lv_obj_set_size(link_pill,148,34);lv_obj_set_style_radius(link_pill,17,0);
    link_dot=lv_obj_create(link_pill);flat(link_dot,Accent);lv_obj_set_pos(link_dot,14,13);lv_obj_set_size(link_dot,8,8);lv_obj_set_style_radius(link_dot,4,0);
    link_label=label(link_pill,"",30,10,112,&lv_font_montserrat_12,0xA8F2CA);link_shown=-1;update_link();
    clock_label=label(header,"--:--",890,25,114,&lv_font_montserrat_22,Text);lv_obj_set_style_text_align(clock_label,LV_TEXT_ALIGN_RIGHT,0);
    auto *rule=lv_obj_create(header);flat(rule,Accent);lv_obj_set_pos(rule,0,Header-2);lv_obj_set_size(rule,W,2);
    lv_obj_set_style_bg_grad_color(rule,lv_color_hex(HeaderBg),0);lv_obj_set_style_bg_grad_dir(rule,LV_GRAD_DIR_HOR,0);
    grid=lv_obj_create(screen);flat(grid,Bg);lv_obj_set_pos(grid,0,Header);lv_obj_set_size(grid,W,H-Header);
    for(lv_indev_t *indev=lv_indev_get_next(nullptr);indev;indev=lv_indev_get_next(indev))lv_indev_add_event_cb(indev,wake_touch,LV_EVENT_PRESSED,nullptr);
    build_ambient();
    rebuild();update_context();lv_screen_load(screen);update(nullptr);lv_timer_create(update,40,nullptr);
}
extern "C" int ui_debug_visible_text(char *out,size_t size) {
    if(!out||!size)return -1;
    const auto context=deck_model_context();
    const int n=snprintf(out,size,"{\"screen\":\"%s\",\"buttons\":%d,\"profile\":\"%s\",\"page\":\"%s\",\"canBack\":%s,\"pc\":%s}",
                         deck_model_screen()==DECK_SCREEN_AMBIENT?"ambient":"deck",deck_model_button_count(),context.profile,context.page,context.can_go_back?"true":"false",link_shown==1?"true":"false");
    return n>0&&n<static_cast<int>(size)?0:-1;
}
