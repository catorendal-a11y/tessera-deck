#pragma once
#include <lvgl.h>
#include <stdint.h>
#include <string.h>
#include "icon_pack_map.h"

// Lucide 1.59.0 pinned PUA map. Existing IDs must never be reassigned.
extern const lv_font_t deck_lucide_60;
static inline bool deck_lucide_glyph(const char* name,char out[5]) {
    if(!name||strlen(name)!=7||strncmp(name,"lc:",3))return false;
    uint32_t code=0;
    for(int i=3;i<7;++i) {
        const char c=name[i];
        int value=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;
        if(value<0)return false;
        code=(code<<4)|value;
    }
    if(code<DECK_LUCIDE_FIRST||code>DECK_LUCIDE_LAST)return false;
    const uint32_t offset=code-DECK_LUCIDE_FIRST;
    if(!(deck_lucide_mask[offset/8]&(1u<<(offset%8))))return false;
    out[0]=0xe0|(code>>12);out[1]=0x80|((code>>6)&0x3f);
    out[2]=0x80|(code&0x3f);out[3]=0;
    return true;
}
