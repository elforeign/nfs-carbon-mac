#include "host.h"
#include "carbon_pad_layout.h"
#include <CoreGraphics/CoreGraphics.h>
#include <CoreText/CoreText.h>
#include <math.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <strings.h>
#include "carbon_padprompts_glyphs.h"
#include "carbon_padprompts_xboxart.h"
#include "carbon_texture_abi.h"

static uint32_t prompt_hash(const char *s) {
    uint32_t hash=UINT32_MAX;
    for (;*s;++s) hash=hash*33+(unsigned char)(*s>='a'&&*s<='z'?*s-32:*s);
    return hash;
}
static const struct { const char *name; int art; } glyphs[]={
    {"CROSS",A_CROSS},{"TRIANGLE",A_TRIANGLE},{"CIRCLE",A_CIRCLE},{"SQUARE",A_SQUARE},
    {"L1",A_L1},{"R1",A_R1},{"L2",A_L2},{"R2",A_R2},{"L3",A_L3},{"R3",A_R3},
    {"START",A_OPTIONS},{"SELECT",A_CREATE},{"DPAD",A_DPAD},{"DPAD_UP",A_DPAD_UP},
    {"DPAD_DOWN",A_DPAD_DOWN},{"DPAD_LEFT",A_DPAD_LEFT},{"DPAD_RIGHT",A_DPAD_RIGHT},
    {"DPAD_LEFTRIGHT",A_DPAD_LEFTRIGHT},{"LEFT_ANALOG",A_LSTICK},{"RIGHT_ANALOG",A_RSTICK},
    {"RIGHT_ANALOG_UP",A_RSTICK_UP},{"RIGHT_ANALOG_DOWN",A_RSTICK_DOWN},
    {"L1_LOADING",A_L1},{"R1_LOADING",A_R1}
};
#define GLYPHS (sizeof glyphs/sizeof *glyphs)
static uint32_t hashes[GLYPHS], private_hashes[GLYPHS], textures[GLYPHS];
static int initialized;
#include "carbon_padprompts_xbox.h"
static _Atomic int active_pad=-1;
static _Atomic int physical_input, pad_connected;
static int prompt_mode=-1;
static int mode(void) {
    if (prompt_mode<0) {
        const char *s=getenv("NFS_BUTTON_PROMPTS");
        prompt_mode=s&&!strcasecmp(s,"pc")?0:s&&!strcasecmp(s,"console")?1:2;
    }
    return prompt_mode;
}
/* Controller input hides the system pointer once per takeover. Events that
 * can show it again re-arm the request, including fractional mouse movement. */
void user32_hide_pointer(void);
static _Atomic int pointer_hidden;
void prompts_pointer_visible(void) { atomic_store(&pointer_hidden,0); }
static void prompts_activity(int pad, int physical) {
    static float moved;
    if (pad!=1) prompts_pointer_visible();
    if (pad<0) { moved+=1; if (moved<16) return; pad=0; }
    moved=0;
    if (pad==1 && !atomic_exchange(&pointer_hidden,1)) user32_hide_pointer();
    if(physical)atomic_store_explicit(&physical_input,pad==1,memory_order_relaxed);
    int previous=atomic_exchange(&active_pad,pad==1);
    if(diag_on && previous!=(pad==1))diag_event("carbon prompts input=%s",pad==1?"controller":"keyboard");
}
void prompts_input(int pad) {
    prompts_activity(pad,1);
}
void prompts_mouse_moved(float points) {
    if (points>0) prompts_pointer_visible();
    for (float n=points;n>=1;n-=1) prompts_input(-1);
}
void prompts_pad_seen(int connected) {
    atomic_store_explicit(&pad_connected,!!connected,memory_order_relaxed);
    if (connected && atomic_load(&active_pad)<0) prompts_activity(1,0);
    if (!connected) atomic_store(&active_pad,0);
}
/* Physical activity only: prompt defaults and disconnects retain the last source. */
int prompts_physical_input(void) { return atomic_load_explicit(&physical_input,memory_order_relaxed); }
/* UI callers retain the existing prompt-state semantics. */
int prompts_last_input(void) { return atomic_load(&active_pad); }
int prompts_pad_connected(void) { return atomic_load_explicit(&pad_connected,memory_order_relaxed); }
int carbon_addons_host_osk_pad(int, uint32_t, int, int, int, int, float, float, int, int);
int osk_pad(int port,uint32_t buttons,int up,int down,int left,int right,
            float lx,float ly,int connected,int xbox) {
    if(port==0) {
        if(!connected)prompts_activity(0,0);
        else if(buttons || up || down || left || right || fabsf(lx)>.2f || fabsf(ly)>.2f)prompts_input(1);
    }
    return carbon_addons_host_osk_pad(port, buttons, up, down, left, right, lx, ly, connected, xbox);
}
static int console_layout(void) {
    int family=carbon_pad_layout_get();
    return (family==CARBON_LAYOUT_PLAYSTATION || (family==CARBON_LAYOUT_XBOX && (xbox_assets() || xbox_prompt_art()))) &&
           mode() && (mode()==1 || atomic_load(&active_pad)==1);
}
static uint32_t family_hash(unsigned i) {
    return carbon_pad_layout_get()==CARBON_LAYOUT_XBOX?xbox_hashes[i]:private_hashes[i];
}
static void initialize(void) {
    if (initialized) return;
    for (unsigned i=0;i<GLYPHS;++i) {
        char name[64]; snprintf(name,sizeof name,"PADPROMPT_%s",glyphs[i].name);
        hashes[i]=prompt_hash(glyphs[i].name); private_hashes[i]=prompt_hash(name);
        snprintf(name,sizeof name,"PADPROMPT_XBOX_%s",glyphs[i].name);
        xbox_hashes[i]=prompt_hash(name);
    }
    initialized=1;
}
static int glyph_index(uint32_t hash) {
    initialize();
    for (unsigned i=0;i<GLYPHS;++i) if (hashes[i]==hash || private_hashes[i]==hash || (xbox_hashes[i] && xbox_hashes[i]==hash)) return (int)i;
    return -1;
}
static void pixels_draw(int art,const char *xbox,uint8_t pixels[CT_SIZE]) {
    CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
    CGContextRef g=CGBitmapContextCreate(pixels,CT_SIDE,CT_SIDE,8,CT_SIDE*4,cs,
                                        kCGImageAlphaPremultipliedFirst|kCGBitmapByteOrder32Little);
    CGColorSpaceRelease(cs);
    if (!g) return;
    CGContextClearRect(g,CGRectMake(0,0,CT_SIDE,CT_SIDE));
    CGContextScaleCTM(g,.5,.5);
    if(xbox)draw_xbox_art(g,xbox);else draw_art(g,art); CGContextFlush(g); CGContextRelease(g);
    for (unsigned i=0;i<CT_SIDE*CT_SIDE;++i) {
        uint8_t *p=pixels+4*i,a=p[3];
        if (a && a<255) for (int k=0;k<3;++k) p[k]=(p[k]*255+a/2)/a;
    }
}
static uint32_t glyph_texture(Cpu *c,unsigned i) {
    if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {
        if(!xbox_assets()) {
            if(!xbox_prompt_art())return 0;
            initialize();
            if(!xbox_textures[i]) {
                uint8_t pixels[CT_SIZE]={0};pixels_draw(glyphs[i].art,glyphs[i].name,pixels);
                xbox_textures[i]=carbon_texture_new(xbox_hashes[i],glyphs[i].name,pixels);
                if(diag_on)diag_event("carbon Xbox port art name=%s ti=%08X",glyphs[i].name,xbox_textures[i]);
            }
        }
        return carbon_texture_ready(c,xbox_textures[i])?xbox_textures[i]:0;
    }
    if (!textures[i]) {
        uint8_t pixels[CT_SIZE]={0}; pixels_draw(glyphs[i].art,NULL,pixels);
        textures[i]=carbon_texture_new(private_hashes[i],glyphs[i].name,pixels);
    }
    return carbon_texture_ready(c,textures[i])?textures[i]:0;
}
/* Private hashes serve images, native glyph IDs and both inline-text drawing
 * and measurement/cache lookups. Ordinary currency strings never enter here. */
void carbon_padprompts_lookup(Cpu *c,void (*original)(Cpu *)) {
    uint32_t hash=arg(c,0); int i=glyph_index(hash);
    if((hash==0xEC3C0443u || hash==0xEC3C0444u) && console_layout() &&
       carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {
        uint32_t ti=xbox_diagrams[hash-0xEC3C0443u];
        if(carbon_texture_ready(c,ti)) {c->eax=ti;c->esp+=4;return;}
    }
    if (i>=0 && console_layout()) {
        uint32_t ti=glyph_texture(c,(unsigned)i);
        if (ti) { c->eax=ti; c->esp+=4; return; }
    }
    original(c);
}
void carbon_padprompts_id(Cpu *c,void (*original)(Cpu *)) {
    original(c);
    if (console_layout()) { int i=glyph_index(c->eax); if(i>=0)c->eax=family_hash(i); }
}

static int diagram_analog(Cpu *c) {
    Cpu property=*c;property.esp-=128;property.ecx=0x00A8AD30u;
    uint32_t out=property.esp-32;M32(out)=1;
    uint32_t args[]={0x13A7,out,0,UINT32_MAX,UINT32_MAX};
    call_guest(&property,0x004A0490u,5,args);
    return M32(out)!=0;
}

/* These are native callout channels, not configuration recipes. Resolve their
 * captions from the current player-zero records, including custom assignments. */
static const struct { unsigned type,object; } diagram_channels[17]={
    {2,4},{4,0},{2,5},{2,3},{2,1},{2,0},{2,2},{3,0},{3,3},
    {3,1},{3,2},{5,2},{7,2},{2,6},{6,1},{7,1},{2,7}
};
static uint32_t action_label(unsigned action) {
    if((action>=9 && action<=17) || action==27)return 0; /* No native caption for these wheel/capture roles. */
    if(action==3)return prompt_hash("CTRL_GAMEACTION_STEERLEFT"); /* Both directions share Steer. */
    if(action==23)return prompt_hash("FE_ACTION_B2");
    uint32_t name=M32(0x00A98700u+8u*action);
    if(!name)return 0;
    const char *source=gptr(name), *suffix=NULL, *prefix=NULL;
    if(!strncmp(source,"GAME_ACTION_",12)) {prefix="CTRL_GAMEACTION_";suffix=source+12;}
    else if(!strncmp(source,"CAM_ACTION_",11)) {prefix="CTRL_CAMERAACTION_";suffix=source+11;}
    else if(!strncmp(source,"HUDACTION_",10)) {prefix="CTRL_HUDACTION_";suffix=source+10;}
    if(!suffix)return 0;
    char label[96];snprintf(label,sizeof label,"%s%s",prefix,suffix);
    return prompt_hash(label);
}
static uint32_t diagram_label(Cpu *c,unsigned slot,unsigned pad) {
    if(slot>=17 || pad>=16 || pad>=M32(0x00A98948u))return 0;
    unsigned type=diagram_channels[slot].type,object=diagram_channels[slot].object;
    if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {
        if(slot==0) {type=5;object=2;} /* LT */
        if(slot==2) {type=7;object=2;} /* RT */
        if(slot==11) {type=2;object=4;} /* LB */
        if(slot==12) {type=2;object=5;} /* RB */
    }
    if(!diagram_analog(c)) {
        if(slot==1) {type=3;object=3;} /* C2's main callout ends at the D-pad. */
        else if(slot>=7 && slot<=10) {
            static const unsigned types[]={4,4,5,5},axes[]={1,0,0,1};
            type=types[slot-7];object=axes[slot-7]; /* Auxiliary callouts move to the left stick. */
        }
    }
    for(unsigned action=0;action<=28;++action) {
        uint32_t base=M32(0x00A98704u+8u*action);
        if(!base)continue;
        for(unsigned s=0;s<2;++s) {
            uint32_t record=base+12u*(2+2*pad+s);
            if(M32(record)==type && M32(record+4)==pad &&
               M32(record+8)==object) {
                uint32_t label=action_label(action);if(label)return label;
            }
        }
    }
    return 0;
}
void carbon_padprompts_label(Cpu *c,void (*original)(Cpu *)) {
    if(!console_layout()) {original(c);return;}
    c->eax=diagram_label(c,arg(c,1),arg(c,2));c->esp+=4; /* cdecl, three caller-popped arguments */
}
#define DIAGRAM_SLOTS 8u
typedef struct {
    uint32_t package,name,image,aux,labels[17],buttons[17],extras[3],signature,loading,last_ti,last_device;
    uint64_t frame;
} PromptDiagram;
static PromptDiagram diagrams[DIAGRAM_SLOTS];
static unsigned next_diagram;
static unsigned diagram_begin(uint32_t package,const char *name) {
    if(!strncasecmp(name,"WS_",3))name+=3;
    if(strcasecmp(name,"Loading_Controller.fng") && strcasecmp(name,"FeControllerConfig.fng"))return 0;
    unsigned i=next_diagram++%DIAGRAM_SLOTS;
    diagrams[i]=(PromptDiagram){.package=package,.name=M32(package+0xC),.loading=!strcasecmp(name,"Loading_Controller.fng"),.last_ti=UINT32_MAX,.frame=UINT64_MAX};
    return i+1;
}
static void diagram_object(unsigned index,uint32_t o) {
    if(!index)return;
    PromptDiagram *d=diagrams+index-1;
    if(M32(o+0x10)==0x922A39C4u || M32(o+0x10)==0x4592229Cu)d->image=o;
    if(M32(o+0x10)==0xF29E7840u)d->aux=o;
    const uint32_t hidden[]={0x0F274B86u,0x673D77BCu,0x351AE442u};
    for(unsigned i=0;i<3;++i)if(M32(o+0x10)==hidden[i])d->extras[i]=o;
    for(unsigned slot=0;slot<17;++slot) {
        char name[32];snprintf(name,sizeof name,"CButton_%u",slot+1);
        if(M32(o+0x10)==prompt_hash(name))d->labels[slot]=o;
        snprintf(name,sizeof name,"BUTTON_%u",slot+1);
        if(M32(o+0x10)==prompt_hash(name))d->buttons[slot]=o;
    }
}
/* SHOW resets the stored placeholder textures. Bind each surviving BUTTON_n
 * to its native ID at draw time, so L2/R2 and Start cannot retain retail art. */
static uint32_t diagram_glyph(Cpu *c,unsigned index,uint32_t object) {
    if(!index)return 0;
    PromptDiagram *d=diagrams+index-1;
    if(d->aux==object && !diagram_analog(c)) {
        int i=glyph_index(prompt_hash("LEFT_ANALOG"));return i>=0?family_hash(i):0;
    }
    for(unsigned slot=0;slot<17;++slot)if(d->buttons[slot]==object) {
        uint32_t name=M32(0x00A5E958u+4u*slot);
        int i=name?glyph_index(prompt_hash(gptr(name))):-1;
        if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX && (slot==11 || slot==12))
            i=glyph_index(prompt_hash(slot==11?"R2":"L2"));
        return i>=0?family_hash(i):0;
    }
    return 0;
}
static void diagram_visible(uint32_t o,int visible) {
    if(o)M32(o+0x1C)=(M32(o+0x1C)&~1u)|(visible?0:1u)|0x2400000u;
}
static void diagram_refresh(Cpu *c,unsigned index,int con) {
    if(!index)return;
    PromptDiagram *d=diagrams+index-1;
    if(d->frame==perf_nframes)return;
    d->frame=perf_nframes;
    uint32_t signature=((con+1)*3u+diagram_analog(c))*3u+carbon_pad_layout_get();
    for(unsigned action=0;action<=28;++action) {
        uint32_t base=M32(0x00A98704u+8u*action);
        if(!base)continue;
        for(unsigned n=0;n<6;++n)signature=signature*33+M32(base+24+4*n);
    }
    if(signature==d->signature)return;
    d->signature=signature;
    if(d->loading) {
        /* The native constructor explicitly hides this entire controller group. */
        Cpu state=*c;state.esp-=128;
        uint32_t args[]={d->name,0x3248E720u,prompt_hash(con?"SHOW":"HIDE"),1};
        call_guest(&state,0x005A02C0u,4,args);
    }
    for(unsigned slot=0;slot<17;++slot) {
        uint32_t label=con?diagram_label(c,slot,0):0;
        diagram_visible(d->labels[slot],label!=0);diagram_visible(d->buttons[slot],label!=0);
        if(label && d->labels[slot]) {
            Cpu text=*c;text.esp-=128;
            uint32_t args[]={d->name,M32(d->labels[slot]+0x10),label};
            call_guest(&text,0x005A0830u,3,args);
        }
    }
    for(unsigned i=0;i<3;++i)diagram_visible(d->extras[i],0); /* Native unused label and loading shoulders. */
    if(diag_on)diag_event("carbon diagram captions layout=%d input=%d signature=%08X",carbon_pad_layout_get(),atomic_load(&active_pad),signature);
}

#define OBJECT_SLOTS 32768u
typedef struct { uint32_t object,hash; unsigned keep,cap,diagram; } PromptObject;
static PromptObject objects[OBJECT_SLOTS];
static PromptObject *object_info(uint32_t o,int create) {
    unsigned slot=(o>>3)&(OBJECT_SLOTS-1);
    for (unsigned n=0;n<OBJECT_SLOTS;++n,slot=(slot+1)&(OBJECT_SLOTS-1)) {
        PromptObject *p=objects+slot;
        if (p->object==o) return p->hash==M32(o+0x10)||create?p:NULL;
        if (!p->object) return create?p:NULL;
    }
    return NULL;
}
static int has_console(uint32_t head,unsigned budget) {
    for (unsigned n=0;head && n<budget;++n,head=M32(head+4)) {
        if (M32(head+0x1C)&0x40) return 1;
        if (M32(head+0x18)==5 && has_console(M32(head+0x64),M32(head+0x60)))return 1;
    }
    return 0;
}
/* The three PC-only packages have seven decoded action images. Scope by package
 * and keycap: preserve their widgets, including controls/capture and rumble. */
static uint32_t action_cap(const char *package,uint32_t texture) {
    if (!strcasecmp(package,"Options_PC_Controller.fng")) {
        if(texture==prompt_hash("PC_KEY_ESC"))return prompt_hash("TRIANGLE"); /* Done/Cancel */
        if(texture==prompt_hash("PC_KEY_1"))return prompt_hash("CIRCLE"); /* Defaults/B5 */
        if(texture==prompt_hash("PC_KEY_2"))return prompt_hash("SQUARE"); /* Clear/B4 */
        if(texture==prompt_hash("PC_KEY_4"))return prompt_hash("R3"); /* Rumble/B3 */
    }
    if (!strcasecmp(package,"Loading_Tips.fng") || !strcasecmp(package,"FeOnlineChatDialog.fng")) {
        if(texture==prompt_hash("PC_KEY_ENTER"))return prompt_hash("CROSS"); /* Continue/Accept */
        if(texture==prompt_hash("PC_KEY_ESC"))return prompt_hash("TRIANGLE"); /* Cancel */
    }
    if (!strcasecmp(package,"FeOptionsScreen.fng") && texture==prompt_hash("PC_KEY_2"))
        return prompt_hash("SQUARE"); /* Advanced/B4 */
    return 0;
}
/* Video > Advanced exists only on the PC: the console hint set of this package
 * has Done, Defaults and Select but no twin of PC_HELP_TWO, so that group stays. */
static int pc_only_hint(const char *package,uint32_t object) {
    return !strcasecmp(package,"FeOptionsScreen.fng") && object==prompt_hash("PC_HELP_TWO");
}
static void catalogue_objects(uint32_t head,unsigned budget,int keep,const char *package,unsigned diagram) {
    for(unsigned n=0;head && n<budget;++n,head=M32(head+4)) {
        PromptObject *p=object_info(head,1);
        int kept=keep || pc_only_hint(package,M32(head+0x10));
        if (p) *p=(PromptObject){head,M32(head+0x10),kept,
                       kept && M32(head+0x18)==1?action_cap(package,M32(head+0x24)):0,
                       diagram};
        diagram_object(diagram,head);
        if(M32(head+0x18)==5)catalogue_objects(M32(head+0x64),M32(head+0x60),kept,package,diagram);
    }
}
void carbon_padprompts_loaded(Cpu *c,void (*original)(Cpu *)) {
    uint32_t package=arg(c,0);
    original(c);
    const char *name=gptr(M32(package+0xC));
    if (!name) name="";
    uint32_t head=M32(package+0x4C);
    catalogue_objects(head,32768,!has_console(head,32768),name,diagram_begin(package,name));
}
void carbon_padprompts_visit(Cpu *c,void (*original)(Cpu *)) {
    (void)original;
    uint32_t o=arg(c,0),flags=M32(o+0x1C);
    if(flags&0x40)M32(o+0x1C)=(flags&~0x10000000u)|0x400000u;
    if(M32(o+0x18)==5 && (flags&0x48))
        for(uint32_t child=M32(o+0x64),n=M32(o+0x60);child && n;child=M32(child+4),--n)
            M32(child+0x1C)|=flags&0x48;
    c->eax=(c->eax&~255u)|1u; c->esp+=8;
}

static uint32_t diagram_request;
static uint32_t diagram_texture(Cpu *c) {
    if(carbon_pad_layout_get()==CARBON_LAYOUT_XBOX) {
        unsigned index=!diagram_analog(c);
        return xbox_assets() && carbon_texture_ready(c,xbox_diagrams[index])?0xEC3C0443u+index:0;
    }
    if (!diagram_request) {
        diagram_request=gmalloc(8); M32(diagram_request)=0xDF7BB408u;M32(diagram_request+4)=0xDF7BB409u;
        Cpu load=*c;load.esp-=128;
        uint32_t args[]={diagram_request,2,0,0,7,UINT32_MAX};
        call_guest(&load,0x00560080u,6,args);
    }
    return diagram_analog(c)?0xDF7BB408u:0xDF7BB409u;
}
static void diagram_diagnostics(Cpu *c,unsigned index,uint32_t object,uint32_t hash) {
    if(!diag_on || !index)return;
    PromptDiagram *d=diagrams+index-1;
    Cpu lookup=*c;lookup.esp-=128;
    uint32_t args[]={hash,0,0};uint32_t ti=call_guest(&lookup,0x0055CFD0u,3,args);
    uint32_t platform=ti?M32(ti):0,device=platform?M32(platform+0x10):0;
    if(d->last_ti==ti && d->last_device==device)return;
    d->last_ti=ti;d->last_device=device;
    diag_event("carbon diagram picture=%08X draw=%08X ti=%08X size=%ux%u d3d=%08X flags=%08X cache=%08X",
               M32(object+0x10),hash,ti,ti?M16(ti+0x28):0,ti?M16(ti+0x2A):0,device,M32(object+0x1C),M32(object+0x58));
}
static void render_count(unsigned attempted,unsigned drawn,unsigned missing,unsigned cap,uint32_t art) {
    if (!diag_on) return;
    static uint64_t frame=UINT64_MAX;
    static unsigned attempts,draws,misses,caps,xb,ps,xbd,psd;
    static uint32_t witnessed[2][GLYPHS];
    static FILE *out;
    if (!out) { char path[1100];snprintf(path,sizeof path,"%s/carbon_prompts.tsv",diag_dir);out=fopen(path,"w"); }
    if (frame!=perf_nframes) {
        if(out && frame!=UINT64_MAX)fprintf(out,"%llu\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\n",frame,attempts,draws,misses,caps,xb,ps,xbd,psd);
        frame=perf_nframes; attempts=draws=misses=caps=xb=ps=xbd=psd=0;
    }
    attempts+=attempted;draws+=drawn;misses+=missing;caps+=cap;
    if(art==0xEC3C0443u || art==0xEC3C0444u)++xbd;
    else if(art==0xDF7BB408u || art==0xDF7BB409u)++psd;
    else if(art)for(unsigned i=0;i<GLYPHS;++i) {
        unsigned family=art==xbox_hashes[i];
        if(!family && art!=private_hashes[i])continue;
        if(family)++xb;else ++ps;
        uint32_t ti=family?xbox_textures[i]:textures[i],pl=ti?M32(ti):0,device=pl?M32(pl+0x10):0;
        if(device && witnessed[family][i]!=device) {
            witnessed[family][i]=device;
            diag_event("carbon prompt glyph family=%s name=%s hash=%08X ti=%08X d3d=%08X",
                       family?"Xbox":"PlayStation",glyphs[i].name,art,ti,device);
        }
        break;
    }
}
void carbon_padprompts_render(Cpu *c,void (*original)(Cpu *)) {
    uint32_t o=arg(c,0),oldtex=0,sub=0;
    int con=console_layout(); PromptObject *info=object_info(o,0);
    if(info)diagram_refresh(c,info->diagram,con);
    uint32_t flags=M32(o+0x1C),type=M32(o+0x18);
    if (con && type==1) {
        oldtex=M32(o+0x24);
        int i=glyph_index(oldtex);
        if(i>=0)sub=family_hash(i);
        if(info && info->cap) { i=glyph_index(info->cap);if(i>=0)sub=family_hash(i); }
        if(info && info->diagram) {uint32_t glyph=diagram_glyph(c,info->diagram,o);if(glyph)sub=glyph;}
        if(info && info->diagram && (M32(o+0x10)==0x4592229Cu || M32(o+0x10)==0x922A39C4u))sub=diagram_texture(c);
    }
    int skip=con?(flags&8) && !(info && info->keep):flags&0x40;
    if(skip) {render_count(!!(flags&0x40),0,0,0,0);c->esp+=8;return;}
    if(sub) {M32(o+0x24)=sub;M32(o+0x1C)|=0x2000000u;}
    if(con)M32(o+0x1C)&=~0x40u;
    original(c);
    if(info && sub && (sub==0xDF7BB408u || sub==0xDF7BB409u || sub==0xEC3C0443u || sub==0xEC3C0444u))diagram_diagnostics(c,info->diagram,o,sub);
    if(flags&0x40)M32(o+0x1C)|=0x40u;
    if(sub) {M32(o+0x24)=oldtex;M32(o+0x1C)|=0x2000000u;}
    render_count(!!(flags&0x40),con && (flags&0x40) && !(flags&1),0,sub && info && info->cap,(flags&1)?0:sub);
}

/* 0066E300 (ELoadingScreenOn, ESI = the event, type +8) is the only caller. Type 1 is the load into the front end
 * (EQuitToFE 006715D0, front-end load 006B8030); a crew intro started there waits for the loading screen's screen
 * object to hand back (0059B1B0), and Loading_Controller.fng has none, so those loads keep the retail tips screen. */
static int loads_front_end(Cpu *c) { return M32(c->esp)==0x0066E3B7u && M32(c->esi+8)==1; }
/* Diagnostic: retype the EQuitToFE being built (caller 006715D0, its ESI saved at esp+10) to reproduce a front-end
 * return such as JumpToNewWingMan (12) from any quit to the front end. "12:Name" also sets the pending front-end
 * movie as the story script's SetPendingFEMovie does (00667E44: 00617820 thiscall [00A982B8], string into +0x126);
 * string property 6050, which the crew manager (008456B0) plays, is read-only and returns that string (004B2A01 ->
 * 004A16D0). */
static void diag_quit_type(Cpu *c) {
    static int type=-1; static const char *movie;
    if(type<0) {
        const char *s=getenv("NFS_CARBON_DIAG_QUITTYPE"); type=s?atoi(s):0;
        movie=s?strchr(s,':'):NULL; if(movie && (!movie[1] || strlen(movie+1)>=48))movie=NULL; else if(movie)++movie;
    }
    if(type<=0 || M32(c->esp+0x24)!=0x00671642u)return;
    uint32_t quit=M32(c->esp+0x10);
    diag_event("carbon diag quit-to-fe type %u -> %d movie=%s",M32(quit+8),type,movie?movie:"");
    M32(quit+8)=(uint32_t)type;
    if(!movie || !M32(0x00A982B8u))return;
    Cpu call=*c; call.esp-=64; uint32_t text=call.esp; unsigned char saved[64]; size_t n=strlen(movie);
    memcpy(saved,G+text,sizeof saved); memcpy(G+text,movie,n+1); call.ecx=M32(0x00A982B8u);
    uint32_t args[]={text};
    call_guest(&call,0x00617820u,1,args);
    memcpy(G+text,saved,sizeof saved);
}
/* Offer the native controller screen for active console input, preserving the viewer. */
void carbon_padprompts_loading(Cpu *c,void (*original)(Cpu *)) {
    if(diag_on)diag_quit_type(c);
    int front_end=loads_front_end(c);
    original(c);
    uint32_t manager=M32(0x00A97A7Cu);
    if(console_layout() && manager && M32(manager+8)!=1 && !front_end)c->eax=3;
    if(diag_on)diag_event("carbon loading screen event=%d tip=%u",front_end,c->eax);
    /* Loading_Controller.fng has no screen object here, so no tips screen rewrites the "done showing"
     * byte for this load: write what a non-waiting one writes at 005E7716, or step 8 of the load
     * (00762D35) waits on the 0 an earlier waiting tip (Resume Career) left behind. */
    if(c->eax==3)M8(0x00A609ACu)=1;
}
