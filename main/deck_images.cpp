#include "deck_images.h"
#include <map>
#include <mutex>
#include <cstring>
#include <cstdio>

namespace {
std::mutex lock;
std::map<std::string,std::shared_ptr<const DeckImage>> images;
std::vector<uint8_t> staging;
std::string pending;
size_t expected=0;
uint32_t crc=0;
uint32_t crc32(const std::vector<uint8_t>& data) {
    uint32_t c=~0u;
    for(auto b:data){c^=b;for(int n=0;n<8;++n)c=(c>>1)^(0xedb88320u & (0u-(c&1)));}
    return ~c;
}
int hex(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;}
bool id_ok(const char* id) {
    if(strlen(id)!=15||strncmp(id,"im:",3))return false;
    for(int i=3;i<15;++i)if(hex(id[i])<0)return false;
    return true;
}
std::shared_ptr<DeckImage> decode() {
    if(staging.size()!=expected||crc32(staging)!=crc||expected<7||memcmp(staging.data(),"ADI1",4))return {};
    const int w=staging[4],h=staging[5],count=staging[6];
    if(w<1||w>72||h<1||h>72||count<1||count>12)return {};
    auto image=std::make_shared<DeckImage>();image->width=w;image->height=h;
    size_t at=7;
    for(int f=0;f<count;++f) {
        if(at+6>expected)return {};
        uint16_t duration=staging[at]|(staging[at+1]<<8);
        uint32_t len=0;for(int i=0;i<4;++i)len|=uint32_t(staging[at+2+i])<<(8*i);
        at+=6;
        if(duration<40||duration>60000||len%5||len>expected-at)return {};
        const size_t end=at+len;std::vector<uint8_t> pixels;pixels.reserve(w*h*4);
        while(at<end) {
            const int run=staging[at++];
            if(!run||pixels.size()+run*4>size_t(w*h*4))return {};
            for(int n=0;n<run;++n)pixels.insert(pixels.end(),staging.data()+at,staging.data()+at+4);
            at+=4;
        }
        if(pixels.size()!=size_t(w*h*4))return {};
        image->frames.push_back(std::move(pixels));image->durations.push_back(duration);
    }
    return at==expected?image:nullptr;
}
}
std::shared_ptr<const DeckImage> deck_image_get(const char* id) {
    std::lock_guard<std::mutex> guard(lock);
    auto it=images.find(id);return it==images.end()?nullptr:it->second;
}
bool deck_image_command(const char* line,std::string& response) {
    if(!strncmp(line,"AD_IMG_BEGIN ",13)) {
        char id[32]{},extra;unsigned length=0,checksum=0;
        pending.clear();staging.clear();expected=0;
        if(sscanf(line+13,"%31s %u %u %c",id,&length,&checksum,&extra)==3&&id_ok(id)&&length>=7&&length<=320000) {
            pending=id;expected=length;crc=checksum;staging.reserve(length);
        }
    } else if(!strncmp(line,"AD_IMG_DATA ",12)) {
        unsigned offset=0;int consumed=0;
        if(sscanf(line+12,"%u %n",&offset,&consumed)!=1||pending.empty())return true;
        const char* raw=line+12+consumed;size_t len=strlen(raw);
        if(offset!=staging.size()||len%2||len>760||staging.size()+len/2>expected){pending.clear();return true;}
        for(size_t i=0;i<len;i+=2){int a=hex(raw[i]),b=hex(raw[i+1]);if(a<0||b<0){pending.clear();break;}staging.push_back((a<<4)|b);}
    } else if(!strcmp(line,"AD_IMG_END")) {
        auto image=pending.empty()?nullptr:decode();
        if(image) {
            std::lock_guard<std::mutex> guard(lock);
            // Only unreferenced assets can be evicted; LVGL retains shared ownership.
            size_t bytes=0;for(auto& pair:images)for(auto& f:pair.second->frames)bytes+=f.size();
            for(auto it=images.begin();bytes>7*1024*1024&&it!=images.end();) {
                if(it->second.use_count()==1){for(auto& f:it->second->frames)bytes-=f.size();it=images.erase(it);}else ++it;
            }
            if(bytes<8*1024*1024){images[pending]=image;response="AD_IMG_END OK "+pending;}
        }
        if(response.empty())response="AD_IMG_END INVALID";
        pending.clear();std::vector<uint8_t>().swap(staging);expected=0;
    } else return false;
    return true;
}
