/* Image-backed native functions and hardware-free cached input. */
#include "funcs.h"
#include "host.h"
#include "carbon_pad_state.h"
#include "settings.h"
#include <stdlib.h>
#include <ctype.h>
uint8_t *G;
static unsigned checks, failures, reached, capture_calls, pumps, originals[4];
static Cpu evaluated_cpu;
int diag_on;
const char *diag_dir;
static char layout_pref[32];
const char *app_pref(const char *key) { return !strcmp(key,"pad_layout") ? layout_pref : NULL; }
void app_pref_set(const char *key,const char *value) { (void)key;snprintf(layout_pref,sizeof layout_pref,"%s",value); }
Setting *settings_find(const char *key) { (void)key; return NULL; }
void settings_dump(const char *path) { (void)path; }
#include "carbon_pad_layout.c"
void diag_event(const char *fmt, ...) { (void)fmt; }
static int context, kinds[2] = {PAD_KIND_DUALSENSE, PAD_KIND_DUALSENSE};
#define DEVICE 0x100000u
#define OUTPUT 0x110000u
#define PREVIOUS 0x111000u
#define JOY(p) (0x120000u + 0x1000u*(p))
#define KEYBOARD 0x130000u
#define MOUSE 0x140000u
#define STACK 0x300000u
#define PROFILE 0x40000u
#define CONFIG_INDEX (PROFILE+0x24288)
#define CONFIG_ANALOG (PROFILE+0x24280)
static unsigned redraws, dirty;
static char heading[256];
#define CHECK(x) do { ++checks; if(!(x)) { if(failures<12) fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); ++failures; } } while(0)
static Cpu cpu(void) { return (Cpu){.ecx=DEVICE,.esp=STACK,.cw=0x37F}; }
int carbon_pad_context(void) { return context; }
int user32_pad_native(void) { return kinds[0]>=PAD_KIND_DUALSENSE && kinds[0]<=PAD_KIND_EDGE; }
int pad_identity_n(int p,char *name,size_t n) {
    int kind=p<2?kinds[p]:0;
    const char *label=kind==PAD_KIND_DUALSENSE?"Controller (DualSense)":
                      kind==PAD_KIND_DUALSHOCK4?"Controller (DualShock 4)":
                      kind==PAD_KIND_EDGE?"Controller (DualSense Edge)":
                      kind==PAD_KIND_OTHER?"Controller (XBOX 360 For Windows)":"";
    if(name && n)snprintf(name,n,"%s",label);
    return kind;
}
void bad_jump(Cpu *c,uint32_t a) { (void)c;fprintf(stderr,"bad jump %x\n",a);abort(); }
void untranslated(Cpu *c,uint32_t a) { bad_jump(c,a); }
void host_import(Cpu *c,uint32_t a) {
    if(a==0x009C1444u) { c->eax=0;c->esp+=12; }
    else if(a==0x009C1448u) { c->eax=0;c->esp+=32; }
    else bad_jump(c,a);
}
void native_defaults(Cpu *c);
void carbon_padbind_defaults(Cpu *,void (*)(Cpu *));
void dispatch(Cpu *c,uint32_t a) {
    if(a==0x11111111u) { c->eax=c->ecx+0x234; c->esp+=4; }
    else if(a==0x11111112u) { c->eax=M8(KEYBOARD+0x234+arg(c,0))!=0; c->esp+=8; }
    else if(a==0x11111113u) {
        unsigned property=arg(c,0),out=arg(c,1),player=arg(c,2);
        CHECK(property==0x13A9 || property==0x13A7);CHECK(player==0);
        Cpu read=*c;M32(read.esp+4)=out;M32(read.esp+8)=player;
        if(property==0x13A9)f_004A43E0(&read);else f_004A4380(&read);
        c->eax=read.eax;c->esp+=24;
    }
    else if(a==0x11111114u) {
        unsigned property=arg(c,0),value=arg(c,1),player=arg(c,2);
        CHECK(player==0);CHECK(property==0x13A9 || property==0x13A7 || property==0x13A3);
        if(property==0x13A9 || property==0x13A7) {
            Cpu write=*c;M32(write.esp+4)=value;M32(write.esp+8)=player;
            if(property==0x13A9)f_004A4C00(&write);else f_004A4BA0(&write);
        }
        else dirty=value;
        c->eax=1;c->esp+=24;
    }
    else if(a==0x004A0490u)f_004A0490(c);
    else if(a==0x004A04E0u)f_004A04E0(c);
    else if(a==0x004A5700u)f_004A5700(c);
    else if(a==0x0058CC20u) { ++redraws;c->esp+=4; }
    else if(a==0x00578880u)f_00578880(c);
    else if(a==0x005A0910u) {
        CHECK(arg(c,1)==0x4E11CF90);snprintf(heading,sizeof heading,"%s",(char *)G+arg(c,2));c->esp+=4;
    }
    else if(a==0x00689550u) carbon_padbind_defaults(c,native_defaults);
    else if(a==0x0067A340u) f_0067A340(c);
    else if(a==0x006924F0u) f_006924F0(c);
    else if(a==0x00475F90u) f_00475F90(c);
    else bad_jump(c,a);
}
uint32_t call_guest(Cpu *c,uint32_t a,int n,const uint32_t *args) {
    unsigned sp=c->esp;
    for(int i=n-1;i>=0;--i) { c->esp-=4;M32(c->esp)=args[i]; }
    c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,a);c->esp=sp;return c->eax;
}
/* Native defaults asks DirectInput whether the device has a POV. */
void f_0067A0F0(Cpu *c) { c->eax=1; c->esp+=8; }
void f_00679D20(Cpu *c) { ++pumps;c->esp+=4; }
void f_00680E50(Cpu *c) { ++capture_calls;c->esp+=4; }
void f_00731B30(Cpu *c) { (void)c;abort(); }
void f_00890F54(Cpu *c) { memcpy(G+arg(c,0),G+arg(c,1),arg(c,2));c->esp+=4; }
/* Localization/CRT imports are not the subject of the binding-name fixture. */
void f_00471200(Cpu *c) { snprintf((char *)G+arg(c,0),arg(c,2),"%s",(char *)G+arg(c,1));c->esp+=4; }
void f_00475C30(Cpu *c) { (void)c;abort(); }
void f_00578880(Cpu *c) { CHECK(arg(c,2)==0x74B98590);snprintf((char *)G+arg(c,0),arg(c,1),"Configuration");c->esp+=4; }
void f_00572B90(Cpu *c) { CHECK(arg(c,0)==0);c->eax=PROFILE;c->esp+=8; }
void f_00588EA0(Cpu *c) { (void)c;abort(); }
void f_00679310(Cpu *c) { c->eax=0;c->esp+=4; }
void f_006A1560(Cpu *c) { c->eax=0;c->esp+=12; }
void f_006A15A0(Cpu *c) { c->eax=0;c->esp+=32; }
/* Integer text services retain native cursor rewinds (+160). */
void f_00475F90(Cpu *c) {
    unsigned i=M32(c->ecx+0x160), table=M32(c->ecx+0x15C);
    CHECK(i<M32(c->ecx+0x154));
    c->eax=(uint32_t)strtoul((char *)G+M32(table+12*i+4),NULL,10);
    M32(c->ecx+0x160)=i+1;c->esp+=4;
}
void f_00475C10(Cpu *c) {
    const char *format=(char *)G+arg(c,1);
    CHECK(!strcmp(format,"\t%d") || !strcmp(format,"\t\"%s\""));
    if(strstr(format,"%s")) c->eax=snprintf((char *)G+arg(c,0),128,format,(char *)G+arg(c,2));
    else c->eax=snprintf((char *)G+arg(c,0),32,(char *)G+arg(c,1),(int32_t)arg(c,2));c->esp+=4;
}
void f_00475F30(Cpu *c) {
    unsigned i=M32(c->ecx+0x160),table=M32(c->ecx+0x15C);
    CHECK(i<M32(c->ecx+0x154));
    c->eax=M32(table+12*i+4);M32(c->ecx+0x160)=i+1;c->esp+=4;
}
void f_004711B0(Cpu *c) { c->eax=(uint32_t)strlen((char *)G+arg(c,0));c->esp+=4; }
void f_0087ED0A(Cpu *c) { (void)c;abort(); }
void f_00679DA0(Cpu *c) { (void)c;abort(); }
#include "native.inc"
#include "carbon_padbind.c"
static void original_defaults(Cpu *c) { ++originals[0];native_defaults(c); }
static void original_evaluate(Cpu *c) { ++originals[1];native_evaluate(c);evaluated_cpu=*c; }
static void original_rows(Cpu *c) { ++originals[2];native_rows(c); }
static void original_text(Cpu *c) { ++originals[3];native_text(c); }
static uint32_t record(unsigned a,unsigned slot) { return M32(0xA98704+8*a)+12*slot; }
static void binding(unsigned a,unsigned slot,unsigned t,unsigned d,unsigned o) {
    unsigned r=record(a,slot);M32(r)=t;M32(r+4)=d;M32(r+8)=o;
}
static void neutral(unsigned p) {
    unsigned cache=JOY(p)+0x234; memset(G+cache,0,0x230);
    for(unsigned i=0;i<6;++i) M32(cache+(i<3?4*i:0x20C+4*(i-3)))=32767;
    M32(cache+0x220)=0xFFFFFFFF;
}
static void setup(void) {
    memset(carbon_padbind_saved_name,0,sizeof carbon_padbind_saved_name);
    layout_pref[0]=0;unsetenv("NFS_PAD_LAYOUT");
    memset(carbon_padbind_seen,0,sizeof carbon_padbind_seen);
    memset(carbon_padbind_remembered,0,sizeof carbon_padbind_remembered);
    memset(G+DEVICE,0,0x1900); memset(G+OUTPUT,0,0x2000);
    memset(G+0x91F418,0,0x1000); /* Wrong-image stride mutation sentinel. */
    M32(DEVICE+0x20)=OUTPUT; M32(DEVICE+0x1C)=PREVIOUS;
    M32(0xA98948)=2; M32(0xAB0AD0)=1;
    M32(0xA986F4)=KEYBOARD;M32(KEYBOARD)=0x150000;M32(0x15001C)=0x11111112;
    M32(0xA986FC)=MOUSE;M32(MOUSE)=0x151000;M32(0x151004)=0x11111111;
    memset(G+KEYBOARD+0x234,0,256); memset(G+MOUSE+0x234,0,0x230);
    for(unsigned p=0;p<2;++p) {
        M32(0xA986D0+4*p)=JOY(p); M32(JOY(p))=0x152000;
        M32(0x152004)=0x11111111;
        strcpy((char *)G+JOY(p)+0x114,"Controller (DualSense)"); neutral(p);kinds[p]=PAD_KIND_DUALSENSE;
    }
    /* Deliberately noncontiguous allocations distinguish Carbon's directory. */
    for(unsigned a=0;a<72;++a) {
        unsigned base=0x180000+((a*17)%72)*128;
        M32(0xA98700+8*a)=M32(0xA61C88+52*a);M32(0xA98704+8*a)=base;
        memcpy(G+base,G+0xA61C8C+52*a,24);
        for(unsigned p=0;p<2;++p) {
            memcpy(G+base+24+24*p,G+0xA61CA4+52*a,24);
            M32(base+28+24*p)=p;M32(base+40+24*p)=p;
        }
    }
    M32(0xA97BAC)=0;M32(0xA97A78)=0;
    M32(CONFIG_INDEX)=0;M8(CONFIG_ANALOG)=1;
    M32(0xA8AD4C)=0x160000;M32(0x160000)=0x161000;
    M32(0x161018)=0x11111113;M32(0x16101C)=0x11111114;
    redraws=dirty=0;
    context=CARBON_PAD_MENU;
}
static void defaults(unsigned p,int hooked) {
    Cpu c=cpu();M32(c.esp+4)=p;
    if(hooked) carbon_padbind_defaults(&c,original_defaults);else native_defaults(&c);
    CHECK(c.esp==STACK+8);
}
static void evaluate(int hooked) {
    Cpu c=cpu();if(hooked)carbon_padbind_evaluate(&c,original_evaluate);else native_evaluate(&c);
    CHECK(c.esp==STACK+4);
    if(hooked)CHECK(!memcmp(&c,&evaluated_cpu,sizeof c));
}
/* Hook entry wrappers are the same ABI as the registry-generated entries. */
static int retail;
void f_00689550(Cpu *c) {
    if(retail)native_defaults(c);else carbon_padbind_defaults(c,native_defaults);
}
void f_006924F0(Cpu *c) {
    if(retail)native_rows(c);else carbon_padbind_rows(c,native_rows);
}
#ifndef PADPERSIST_OLD
#define PADPERSIST_OLD 0
#endif
void f_00680890(Cpu *c) {
    if(retail || PADPERSIST_OLD)native_hash(c);else carbon_padbind_hash(c,native_hash);
}
void f_004B0270(Cpu *c) {
    if(retail || PADPERSIST_OLD)native_read(c);else carbon_padbind_read(c,native_read);
}
void f_0049DBA0(Cpu *c) {
    if(retail)native_resolve(c);else carbon_padbind_resolve(c,native_resolve);
}
#define PCSET 0x80000u
#define PARSER 0x81000u
#define TOKENS 0x220000u
#define PLAYER_TEXT 0x230000u
#define PAD_TEXT 0x240000u
static void parse_tokens(uint32_t text) {
    unsigned n=0;
    for(uint32_t p=text;M8(p);) {
        while(isspace(M8(p)))++p;
        if(!M8(p))break;
        if(M8(p)=='"') {
            uint32_t value=++p;while(M8(p) && M8(p)!='"')++p;
            CHECK(M8(p)=='"');M8(p++)=0;
            M32(TOKENS+12*n)=0;M32(TOKENS+12*n+4)=value;M32(TOKENS+12*n+8)=0;++n;
            continue;
        }
        M32(TOKENS+12*n)=0;M32(TOKENS+12*n+4)=p;M32(TOKENS+12*n+8)=0;++n;
        while(M8(p) && !isspace(M8(p)))++p;
    }
    CHECK(n<1024);M32(PARSER+0x154)=n;M32(PARSER+0x15C)=TOKENS;M32(PARSER+0x160)=0;
}
static void capture(unsigned action,unsigned slot,unsigned button) {
    M32(0x210004)=0x211000;M32(0x211008)=3;
    M32(0x212000)=2;M32(0x212004)=0;M32(0x212008)=button;
    M32(DEVICE+0x1844)=0;M32(DEVICE+0x1848)=slot;M32(DEVICE+0x184C)=action;
    Cpu c=cpu();M32(c.esp+4)=0x210000;M32(c.esp+8)=0x212000;
    f_0067A130(&c);CHECK(c.esp==STACK+12);
    CHECK(M32(record(action,slot))==2 && M32(record(action,slot)+8)==button);
}
static void save(void) {
    Cpu c=cpu();c.ecx=PROFILE+0x24268;M32(c.esp+4)=PLAYER_TEXT;M32(c.esp+8)=0;
    f_0049DBF0(&c);CHECK(c.esp==STACK+12 && c.eax>PLAYER_TEXT);
    c=cpu();c.ecx=PCSET;M32(c.esp+4)=PAD_TEXT;M32(c.esp+8)=0;
    f_0049E400(&c);CHECK(c.esp==STACK+12 && c.eax>PAD_TEXT);
}
static void load(int reverse) {
    parse_tokens(PLAYER_TEXT);
    Cpu c=cpu();c.ecx=PROFILE+0x24268;M32(c.esp+4)=PARSER;f_0049DCC0(&c);
    CHECK(c.esp==STACK+8);
    /* The load-time resolver only pins collection identity; it applies no recipe. */
    c=cpu();c.ecx=PROFILE+0x24268;M32(c.esp+4)=1;M32(c.esp+8)=1;f_0049DBA0(&c);
    CHECK(c.esp==STACK+12);
    parse_tokens(PAD_TEXT);c=cpu();c.ecx=PCSET;M32(c.esp+4)=PARSER;
    if(reverse!=2) { f_004B0270(&c);CHECK(c.esp==STACK+8); }
    if(reverse==1)defaults(0,!retail);
    evaluate(!retail);
}
static unsigned roundtrip(const char *layout,unsigned number,int broken) {
    setup();strcpy(layout_pref,layout);
    M32(0xA99228)=1;M32(0xA991DC)=1;M32(0xA991E0)=DEVICE;
    M32(0xA98948)=1;
    Cpu c=cpu();carbon_padbind_store(&c,(number-1)%5,number<=5);
    defaults(0,!retail);
    capture(0,2,14);capture(1,2,15);
    unsigned char before[29][24];
    for(unsigned a=0;a<29;++a)memcpy(before[a],G+record(a,2),24);
    unsigned index=M32(CONFIG_INDEX),analog=M8(CONFIG_ANALOG);
    save();
    /* Cold startup: clear provider history and reset native/port defaults. */
    memset(carbon_padbind_seen,0,sizeof carbon_padbind_seen);
    memset(carbon_padbind_remembered,0,sizeof carbon_padbind_remembered);
    M32(CONFIG_INDEX)=0;M8(CONFIG_ANALOG)=1;defaults(0,!retail);
    load(broken);
    unsigned config=(M32(CONFIG_INDEX)!=index)+(M8(CONFIG_ANALOG)!=analog),remaps=0,other=0;
    for(unsigned a=0;a<29;++a) {
        unsigned lost=memcmp(before[a],G+record(a,2),24)!=0;
        if(a<2)remaps+=lost;else other+=lost;
    }
    printf("%s config=%u: properties=%u/2 remaps=%u/2 other=%u/27 lost=%u/31\n",
           layout,number,2-config,2-remaps,27-other,config+remaps+other);
    CHECK(!config);CHECK(!remaps);CHECK(!other);
    return config+remaps+other;
}
#define PROFILE_TEXT 0x250000u
static void disk_file(const char *directory,const char *name,void *data,size_t size,int writing) {
    char path[1024];snprintf(path,sizeof path,"%s/%s",directory,name);
    FILE *f=fopen(path,writing?"wb":"rb");CHECK(f!=NULL);if(!f)exit(2);
    CHECK((writing?fwrite(data,1,size,f):fread(data,1,size,f))==size);CHECK(fclose(f)==0);
}
static unsigned disk_restart(const char *mode,const char *directory) {
    const int writing=!strcmp(mode,"write"),late=strncmp(mode,"late-",5)==0;
    setup();strcpy(layout_pref,"playstation");
    M32(0xA99228)=1;M32(0xA991DC)=1;M32(0xA991E0)=DEVICE;M32(0xA98948)=1;
    unsigned char expected[29][24]={0};unsigned pair[2]={2,1};
    if(!strcmp(mode,"fresh-auto")) {
        defaults(0,1);for(unsigned a=0;a<29;++a)memcpy(expected[a],G+record(a,2),24);
        setup();M32(0xA99228)=1;M32(0xA991DC)=1;M32(0xA991E0)=DEVICE;M32(0xA98948)=1;
        kinds[0]=PAD_KIND_NONE;defaults(0,1);kinds[0]=PAD_KIND_DUALSENSE;evaluate(1);
        for(unsigned a=0;a<29;++a)CHECK(!memcmp(expected[a],G+record(a,2),24));
        printf("fresh automatic: checks=%u failures=%u\n",checks,failures);return 0;
    }
    if(writing) {
        strcpy((char *)G+PROFILE+0x10,"Restart Driver");
        Cpu c=cpu();carbon_padbind_store(&c,2,1);defaults(0,1);
        capture(0,2,14);capture(1,2,15);
        for(unsigned a=0;a<29;++a)memcpy(expected[a],G+record(a,2),24);
        c=cpu();c.ecx=PROFILE;M32(c.esp+4)=PROFILE_TEXT;M32(c.esp+8)=0;
        f_0049B1F0(&c);CHECK(c.esp==STACK+12);save();
    } else {
        strcpy((char *)G+PROFILE+0x10,"NAME");
        if(late)kinds[0]=PAD_KIND_NONE;
        if(!strcmp(mode,"late-auto") || !strcmp(mode,"late-name-auto"))layout_pref[0]=0;
        if(!strcmp(mode,"foreign-controller"))kinds[0]=PAD_KIND_OTHER;
        if(!strcmp(mode,"ambiguous-pads")) { kinds[0]=kinds[1]=PAD_KIND_NONE;M32(0xA98948)=2; }
        if(!strcmp(mode,"foreign-controller") || !strcmp(mode,"ambiguous-pads") ||
           !strcmp(mode,"late-different") || !strcmp(mode,"stale-identity") ||
           !strncmp(mode,"late-name",9))strcpy((char *)G+JOY(0)+0x114,"Controller (XBOX 360 For Windows)");
        defaults(0,1);
    }
    disk_file(directory,"profile.txt",G+PROFILE_TEXT,1024,writing);
    disk_file(directory,"player-settings.txt",G+PLAYER_TEXT,65536,writing);
    disk_file(directory,"controller-settings.txt",G+PAD_TEXT,65536,writing);
    disk_file(directory,"expected-rows.bin",expected,sizeof expected,writing);
    if(writing)return 0;
    parse_tokens(PROFILE_TEXT);Cpu c=cpu();c.ecx=PROFILE;M32(c.esp+4)=PARSER;
    if(strcmp(mode,"missing-name-reader")) { f_0049B230(&c);CHECK(c.esp==STACK+8); }
    load(0);
    unsigned before=0;for(unsigned a=0;a<2;++a)before+=memcmp(expected[a],G+record(a,2),24)==0;
    if(late) { kinds[0]=!strcmp(mode,"late-different")?PAD_KIND_OTHER:PAD_KIND_DUALSENSE;evaluate(1); }
    unsigned name=!strcmp((char *)G+PROFILE+0x10,"Restart Driver");
    unsigned properties=(M32(CONFIG_INDEX)==pair[0])+(M8(CONFIG_ANALOG)==pair[1]),remaps=0,other=0;
    for(unsigned a=0;a<29;++a) {
        unsigned kept=!memcmp(expected[a],G+record(a,2),24);
        if(a<2)remaps+=kept;else other+=kept;
    }
    int rejected=!strcmp(mode,"foreign-controller") || !strcmp(mode,"ambiguous-pads") || !strcmp(mode,"late-different");
    CHECK(name==1);CHECK(properties==2);CHECK(remaps==(rejected?0:2));if(!rejected)CHECK(other==27);
    if(!strcmp(mode,"late-name-resave")) {
        save();
        disk_file(directory,"player-settings.txt",G+PLAYER_TEXT,65536,1);
        disk_file(directory,"controller-settings.txt",G+PAD_TEXT,65536,1);
    }
    printf("disk %s name=%u/1 properties=%u/2 remaps-before-identity=%u/2 remaps=%u/2 other=%u/27 checks=%u failures=%u\n",
           mode,name,properties,before,remaps,other,checks,failures);
    return 32-name-properties-remaps-other;
}
static void hash_oracle(void) {
    const unsigned text=0x260000u;
    for(unsigned byte=1;byte<=255;++byte) {
        M8(text)=byte;M8(text+1)=0;
        Cpu c=cpu();M32(c.esp+4)=text;f_004710B0(&c);
        CHECK(carbon_padbind_name_hash((char *)G+text)==c.eax);
    }
    const char *names[]={"","Controller (DualSense)","Controller (DualShock 4)",
                         "Controller (DualSense Edge)","Controller (XBOX 360 For Windows)",
                         "Controller (\xC3\xA9)"};
    for(unsigned i=0;i<sizeof names/sizeof *names;++i) {
        strcpy((char *)G+text,names[i]);Cpu c=cpu();M32(c.esp+4)=text;f_004710B0(&c);
        CHECK(carbon_padbind_name_hash(names[i])==c.eax);
    }
    printf("native name hash checks=%u failures=%u\n",checks,failures);
}
int main(int argc,char **argv) {
    if(argc!=4 && argc!=6)return 2;G=calloc(1,0xC00000);if(!G)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    if(fread(G,1,0xC00000,f)!=0xC00000)return 2;fclose(f);
    retail=atoi(argv[2]);int broken=atoi(argv[3]);unsigned lost=0;
    if(argc==6 && !strcmp(argv[4],"hash")) { hash_oracle();free(G);return failures?1:0; }
    if(argc==6) { lost=disk_restart(argv[4],argv[5]);free(G);return failures?1:0; }
    lost+=roundtrip("playstation",3,broken);
    lost+=roundtrip("playstation",1,broken);
    lost+=roundtrip("playstation",8,broken);
    lost+=roundtrip("xbox",3,broken);
    lost+=roundtrip("pc",3,broken);
    printf("private_padpersist checks=%u failures=%u lost=%u/155 retail=%d broken=%d\n",
           checks,failures,lost,retail,broken);
    free(G);return failures?1:0;
}
