#include "deck_images.h"
#include <map>
#include <set>
#include <mutex>
#include <cstring>
#include <cstdio>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif

namespace {
std::mutex lock;
std::map<std::string,std::shared_ptr<const DeckImage>> images;
std::vector<uint8_t> staging;
std::string pending;
size_t expected=0;
uint32_t crc=0;
// An upload begun with "ack" (the host saw "imgAck":1) is paced like AD_OTA_DATA: lines of up to ImgChunk bytes, an
// answer every ImgAckBytes and at the end, and INVALID for the first refused line. The longest such line,
// "AD_IMG_DATA 319488 " and 1,024 hex digits, is 1,043 characters and fits main.cpp's line[1100].
// Without "ack" lines stay at 380 bytes (760 digits) and the panel answers only AD_IMG_END.
constexpr size_t ImgChunk=512,ImgAckBytes=2048;  // IMG_CHUNK, IMG_WINDOW in host/panel_serial.py
bool acking=false;
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
// Decoded RGBA bytes kept between pages; PANEL_CACHE_BYTES in host/panel_serial.py, which get_info's "imgCache" overrides.
#ifdef CONFIG_TESSERA_IMAGE_CACHE_KB
constexpr size_t CacheLimit=size_t(CONFIG_TESSERA_IMAGE_CACHE_KB)*1024;  // the S3 boards, main/Kconfig.projbuild
#else
constexpr size_t CacheLimit=8*1024*1024;
#endif
// The host uploads a page's images before its layout and trims its own record only afterwards, so an upload may
// pass CacheLimit by one page of images (18 keys of 72x72x12 frames at 8 MiB, the same share of a smaller cache);
// beyond that an upload is refused.
constexpr size_t UploadLimit=CacheLimit+size_t(uint64_t(18*72*72*4*12)*CacheLimit/(8*1024*1024));
std::map<std::string,uint32_t> last_used;  // insertion order, renewed when a layout uses the image (as on the host)
uint32_t use_tick=0;
uint32_t generation=0;  // bumped per insert: a full cache swaps one image for another without changing the count
size_t image_bytes(const DeckImage& image) {size_t bytes=0;for(auto& f:image.frames)bytes+=f.size();return bytes;}
size_t cache_bytes() {size_t bytes=0;for(auto& pair:images)bytes+=image_bytes(*pair.second);return bytes;}
// Caller holds `lock`. Drops the oldest image that `keep` does not name and, when `idle_only`, no tile shows.
bool evict_oldest(const std::set<std::string>& keep,bool idle_only,const std::string& spare) {
    auto victim=images.end();
    for(auto it=images.begin();it!=images.end();++it) {
        if(it->first==spare||keep.count(it->first)||(idle_only&&it->second.use_count()!=1))continue;
        if(victim==images.end()||last_used[it->first]<last_used[victim->first])victim=it;
    }
    if(victim==images.end())return false;
    last_used.erase(victim->first);images.erase(victim);
    return true;
}
// Caller holds `lock`. Normal eviction waits for the layout (deck_image_keep), which is when the host forgets
// images too; here only an upload past UploadLimit evicts, the least recently used that no tile shows.
bool admit(const std::string& id,const std::shared_ptr<const DeckImage>& image) {
    const size_t incoming=image_bytes(*image);
    if(incoming>CacheLimit)return false;
    auto same=images.find(id);
    const size_t replaced=same==images.end()?0:image_bytes(*same->second);  // a replacement frees its predecessor
    while(cache_bytes()-replaced+incoming>UploadLimit)if(!evict_oldest({},true,id))return false;
    images[id]=image;last_used[id]=++use_tick;++generation;
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
// Appends one AD_IMG_DATA line's hex digits at `offset`; false refuses the upload.
bool append(unsigned offset,const char* raw) {
    const size_t len=strlen(raw);
    if(pending.empty()||offset!=staging.size()||len%2||(acking&&!len)||len>(acking?2*ImgChunk:760)||staging.size()+len/2>expected)return false;
    for(size_t i=0;i<len;i+=2){int a=hex(raw[i]),b=hex(raw[i+1]);if(a<0||b<0)return false;staging.push_back((a<<4)|b);}
    return true;
}
}
std::shared_ptr<const DeckImage> deck_image_get(const char* id) {
    std::lock_guard<std::mutex> guard(lock);
    auto it=images.find(id);
    return it==images.end()?nullptr:it->second;
}
size_t deck_image_cache_limit() {return CacheLimit;}
void deck_image_cache_stats(size_t* bytes,size_t* count) {
    std::lock_guard<std::mutex> guard(lock);
    if(bytes)*bytes=cache_bytes();
    if(count)*count=images.size();
}
void deck_image_keep(const std::vector<std::string>& ids) {
    std::lock_guard<std::mutex> guard(lock);
    std::set<std::string> keep;for(auto& id:ids)if(!id.compare(0,3,"im:"))keep.insert(id);
    for(auto& id:keep)if(images.count(id))last_used[id]=++use_tick;  // sorted, as push_assets moves them to the end
    while(cache_bytes()>CacheLimit&&evict_oldest(keep,false,"")){}
}
uint32_t deck_image_generation() {
    std::lock_guard<std::mutex> guard(lock);
    return generation;
}
bool deck_image_command(const char* line,std::string& response) {
    if(!strncmp(line,"AD_IMG_BEGIN ",13)) {
        char id[32]{},mode[4]{},extra;unsigned length=0,checksum=0;
        pending.clear();staging.clear();expected=0;
        const int fields=sscanf(line+13,"%31s %u %u %3s %c",id,&length,&checksum,mode,&extra);
        acking=fields==4&&!strcmp(mode,"ack");  // a refused upload with "ack" still answers its first line
        if((fields==3||acking)&&id_ok(id)&&length>=7&&length<=320000) {
            pending=id;expected=length;crc=checksum;staging.reserve(length);
        }
    } else if(!strncmp(line,"AD_IMG_DATA ",12)) {
        unsigned offset=0;int consumed=0;
        const bool parsed=sscanf(line+12,"%u %n",&offset,&consumed)==1;
        if(!acking) {  // an unreadable line is skipped, as before "ack"
            if(parsed&&!append(offset,line+12+consumed))pending.clear();
        } else if(parsed&&append(offset,line+12+consumed)) {
            if(staging.size()%ImgAckBytes==0||staging.size()==expected)response="AD_IMG_DATA OK "+std::to_string(staging.size());
        } else {
            pending.clear();acking=false;response="AD_IMG_DATA INVALID";
        }
    } else if(!strcmp(line,"AD_IMG_END")) {
        auto image=pending.empty()?nullptr:decode();
        bool full=false;
        if(image) {
            std::lock_guard<std::mutex> guard(lock);
            full=!admit(pending,image);
            if(!full)response="AD_IMG_END OK "+pending;
        }
        if(response.empty())response=full?"AD_IMG_END FULL":"AD_IMG_END INVALID";
        pending.clear();std::vector<uint8_t>().swap(staging);expected=0;acking=false;
    } else return false;
    return true;
}
