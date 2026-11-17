/* Synthetic resources around the retained translated bodies; no game or I/O. */
#include "funcs.h"
#include "host.h"
#include "heap.h"
#include <stdlib.h>
#include <stdarg.h>
#include "carbon_fix_save.c"
#include "carbon_fix_clock.c"
#include "carbon_fix_model.c"

uint8_t *G;
static uint8_t *image, *saved, *expected;
static Heap *heap;
static unsigned checks, failures, loaded, order[8], original_calls;
static unsigned allocations, callbacks, probes, model_type;
static float timestep = 1.0f / 60.0f;
static int make_callbacks, missing_type = -1, missing_all;
static const uint32_t self = 0x2000, header = 0x3000, base = 0x10000;
static uint32_t records[3], handlers[3];
static const uint32_t sizes[] = {0x10000, 0x12C4, 0x23FA4};
enum { MEMORY = 0xC00000, STACK = 0x200000, TYPE_TABLE = 0x80000,
       RIDE = 0x70000, RESOURCE = 0x60000 };
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); } } while (0)

void *heap_test_memset(void *dst, int c, size_t n) { return memset(dst,c,n); }
static Cpu cpu(void) {
    Cpu c = {0}; c.esp = STACK; c.ecx = self; c.fs_base = 0x1800;
    c.cw = 0x37F; c.ebx = 0xAA; c.esi = 0xBB; c.edi = 0xCC; c.ebp = 0xDD;
    M32(c.esp) = 0xFEED; return c;
}
static void reset(void) {
    memcpy(G,image,MEMORY); loaded=callbacks=allocations=probes=0;
    memset(order,0,sizeof order); missing_type=-1; missing_all=make_callbacks=0;
    M32(0xA97D40)=0xA97D40; M32(0xA97D44)=0xA97D40;
    M32(0xA97CF8)=0xA97CF8;
    M32(self)=0x8000; M32(0x80EC)=0xFF000001; M32(0x8100)=0xFF000002;
    M8(self+0x70)=1; M32(self+0x7C)=header; M32(self+0x84)=base;
    M32(self+0x1C)=7; M32(header+8)=6; M32(header+12)=7;
    M32(0xA9E684)=0;
    M32(0xB74CCC)=TYPE_TABLE;
    strcpy((char *)G+TYPE_TABLE,"MISSING");
    strcpy((char *)G+TYPE_TABLE+0xD0,"VIPER");
    strcpy((char *)G+TYPE_TABLE+2*0xD0,"GOOD");
    M32(self+0x60)=self+0x60; M32(self+0x64)=self+0x60;
}
void bad_jump(Cpu *c,uint32_t at) { (void)c; fprintf(stderr,"bad jump %x\n",at); abort(); }
void untranslated(Cpu *c,uint32_t at) { bad_jump(c,at); }
void host_import(Cpu *c,uint32_t at) { bad_jump(c,at); }
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
    fprintf(stderr,"ABI %x ebx=%x/%x esi=%x/%x edi=%x/%x ebp=%x/%x esp=%x/%x\n",
            fn,c->ebx,b,c->esi,s,c->edi,d,c->ebp,p,c->esp,sp);abort();
}
void f_006A1560(Cpu *c) { c->eax=heap_alloc(heap,arg(c,0));c->esp+=4; }
void f_00471050(Cpu *c) { c->eax=0x1234;c->esp+=4; }
void f_00473570(Cpu *c) { bad_jump(c,0x473570); }
void f_00475230(Cpu *c) { c->eax=0;c->esp+=16; }
void f_00472690(Cpu *c) { c->eax=0;c->esp+=4; }
void f_004721D0(Cpu *c) { c->esp+=4; }
void f_004711B0(Cpu *c) { bad_jump(c,0x4711B0); }
void f_00471280(Cpu *c) { bad_jump(c,0x471280); }
void f_004712C0(Cpu *c) { bad_jump(c,0x4712C0); }
void f_006AABA0(Cpu *c) { bad_jump(c,0x6AABA0); }
void f_0076ACE0(Cpu *c) { x87_push(c,timestep);c->esp+=4; }
void f_00561590(Cpu *c) { ++allocations;c->eax=make_callbacks?0x8000:0;c->esp+=4; }
void f_00672DB0(Cpu *c) {
    CHECK(arg(c,0)==callbacks);CHECK(argf(c,1)==timestep);
    ++callbacks;c->eax=c->ecx;c->esp+=16;
}
void f_00475C10(Cpu *c) {
    uint32_t out=arg(c,0), format=arg(c,1), name=arg(c,2);
    CHECK(!strcmp(gptr(format),"CARS\\%s\\TEXTURES.BIN"));
    c->eax=(uint32_t)sprintf((char *)G+out,gptr(format),gptr(name));c->esp+=4;
}
void f_006B2360(Cpu *c) {
    const char *path=gptr(arg(c,0));int found=0;++probes;
    for (unsigned i=0;i<95;++i) {
        char candidate[128];
        snprintf(candidate,sizeof candidate,"CARS\\%s\\TEXTURES.BIN",gptr(TYPE_TABLE+i*0xD0));
        if (!strcmp(path,candidate)) { found=!missing_all && (int)i!=missing_type;break; }
    }
    c->eax=found?100:0;c->esp+=4;
}
void f_007E44C0(Cpu *c) {
    model_type=M32(arg(c,0));M32(RESOURCE)=RESOURCE;M32(RESOURCE+4)=RESOURCE;
    M32(RESOURCE+0x1174)=0xCAFE;c->eax=RESOURCE;c->esp+=12;
}
uint32_t call_guest(Cpu *c,uint32_t fn,int n,const uint32_t *args) {
    CHECK(fn==0x6B2360 && n==1);
    uint32_t esp=c->esp;c->esp-=4;M32(c->esp)=args[0];
    c->esp-=4;M32(c->esp)=0xFEED;f_006B2360(c);c->esp=esp;return c->eax;
}

#include "native.inc"

void dispatch(Cpu *c,uint32_t target) {
    if(target==0xFF000001) { c->eax=0;c->esp+=8;return; }
    if(target==0xFF000002) { c->eax=0;c->esp+=4;return; }
    if(target==0x57F870) { f_0057F870(c);return; }
    if(target==0x57F900) { f_0057F900(c);return; }
    if(target==0x57F970) { f_0057F970(c);return; }
    unsigned i=target==0x57F910?0:target==0x595A60?1:target==0x57F880?2:3;
    if(i==3) bad_jump(c,target);
    CHECK(loaded<8);if(loaded<8)order[loaded++]=i;
    c->eax=arg(c,0)+sizes[i];c->esp+=12;
}

static void save_setup(int wrong_ids) {
    reset();
    /* Recycle poisoned blocks so native constructor id==0 actually depends on
     * the port allocator's zeroing, rather than initially clean fixture RAM. */
    uint32_t dirty[3];
    for(unsigned i=0;i<3;++i) {
        dirty[i]=heap_alloc(heap,0x14);if(!dirty[i])abort();
        memset(G+dirty[i],0xA5,0x14);
    }
    for(unsigned i=0;i<3;++i)if(!heap_free(heap,dirty[i]))abort();
    Cpu c=cpu();f_00596220(&c);CHECK(c.esp==STACK+4);
    uint32_t node=M32(0xA97D40);
    for(unsigned i=0;i<3;++i) { handlers[i]=node-4;CHECK(M32(handlers[i]+0x10)==0);node=M32(node); }
    CHECK(node==0xA97D40);
    uint32_t p=base+0x30;
    for(unsigned i=0;i<3;++i) {
        records[i]=p;M32(p)=wrong_ids?0xDEADBEEF+i:0;M32(p+4)=sizes[i];
        memset(G+p+0x10,0x60+i,sizes[i]);p+=0x10+sizes[i];
    }
    M32(header+4)=p-base;
}
static void identity(Cpu *c) { (void)c;++original_calls; }
static void save_no_write(void) {
    Cpu c=cpu();memcpy(saved,G,MEMORY);original_calls=0;
    carbon_fix_save_load(&c,identity);CHECK(original_calls==1);
    CHECK(!memcmp(G,saved,MEMORY));
}
static void test_save(int retail_only) {
    save_setup(1);Cpu c=cpu();carbon_orig_00595F90(&c);
    CHECK(loaded==0);printf("K10 retail loaded=%u/3\n",loaded);
    if(retail_only) { CHECK(loaded==3);return; }
    save_setup(1);c=cpu();f_00595F90(&c);
    CHECK(loaded==3);CHECK(order[0]==0 && order[1]==1 && order[2]==2);
    for(unsigned i=0;i<3;++i)CHECK(M32(records[i])==0);
    printf("K10 repaired loaded=%u/3\n",loaded);
    /* Identical-id saves: every guest byte and the complete returned CPU. */
    save_setup(0);c=cpu();memcpy(saved,G,MEMORY);
    Cpu native=c;carbon_orig_00595F90(&native);memcpy(expected,G,MEMORY);
    memcpy(G,saved,MEMORY);loaded=0;f_00595F90(&c);
    CHECK(loaded==3);CHECK(!memcmp(&c,&native,sizeof c));CHECK(!memcmp(G,expected,MEMORY));
    /* Native gate rejects the foreign version before any id repair. */
    save_setup(1);M32(0xA9E684)=1;M32(header+8)=5;save_no_write();
    M32(header+8)=6;M32(header+12)=8;save_no_write();
    save_setup(1);M32(handlers[0])=0xBAD;save_no_write();
    save_setup(1);M32(0xA97D40)=0;save_no_write();
    save_setup(1);M32(0xA97D40)=0xA97D40;save_no_write();
    save_setup(1);M32(header+4)=0xFFFFFFF0;save_no_write();
    save_setup(1);M32(header+4)=0x35;save_no_write();
    save_setup(1);M32(records[0]+4)=0xFFFFFFFF;save_no_write();
    save_setup(1);M32(handlers[2]+4)=handlers[0]+4;save_no_write();
    save_setup(1);M32(header+4)=0x30+0x10+sizes[0];
    M32(handlers[1])=M32(handlers[0]);save_no_write(); /* ambiguous size */
    save_setup(1);M32(records[0]+4)=3;M32(header+4)=0x43;
    c=cpu();f_00595F90(&c);CHECK(loaded==0);CHECK(M32(records[0])==0xDEADBEEF);
    /* Nonzero current handler ids: rewrite to their ids, never assume zero. */
    save_setup(1);for(unsigned i=0;i<3;++i)M32(handlers[i]+0x10)=100+i;
    c=cpu();f_00595F90(&c);CHECK(loaded==3);
    for(unsigned i=0;i<3;++i)CHECK(M32(records[i])==100+i);
}

static double clock_run(float start,unsigned steps,int fixed) {
    reset();MF32(0xB4CFD8)=start;timestep=1.0f/60.0f;
    for(unsigned i=0;i<steps;++i) {
        Cpu c=cpu();M32(c.esp+4)=self;
        if(fixed)f_0076ADA0(&c);else carbon_orig_0076ADA0(&c);
        if(i==0 || i+1==steps) { CHECK(c.esp==STACK+4);CHECK(c.st[c.top]==timestep); }
    }
    CHECK(M32(0xB4CFDC)==steps);CHECK(M32(0xB4CFD4)==steps);
    CHECK(allocations==19*steps);return MF32(0xB4CFD8);
}
static void test_clock(int retail_only) {
    double before=clock_run(20000,600,0);
    CHECK(before==20010.546875);printf("K02 retail 600 ticks: %.6f drift=%.6f%%\n",before,(before-20010)*10);
    if(retail_only) { CHECK(fabs(before-20010)<0.002);return; }
    double after=clock_run(20000,600,1);
    CHECK(fabs(after-20010)<0.002);printf("K02 repaired 600 ticks: %.6f\n",after);
    before=clock_run(600000,600,0);after=clock_run(600000,600,1);
    CHECK(before==600000);CHECK(after==600010);
    printf("K02 stopped clock: %.3f -> %.3f\n",before,after);
    before=clock_run(16400,1,0);CHECK(fabs((before-16400)*60-1)>0.01);
    after=clock_run(16400,600,1);CHECK(fabs(after-16410)<0.002);
    printf("K02 at 16400s native step=%.9f fixed 600 ticks=%.6f\n",before-16400,after-16400);
    before=clock_run(0,984000,0);after=clock_run(0,984000,1);
    CHECK(fabs(after-16400)<0.002);CHECK(fabs(before-16400)>1);
    printf("K02 984000 ticks: native=%.6f repaired=%.6f\n",before,after);
    /* Repeated external zero resets and nonzero writes resynchronize. */
    for(unsigned i=0;i<3;++i) {
        MF32(0xB4CFD8)=0;Cpu c=cpu();M32(c.esp+4)=self;f_0076ADA0(&c);
        CHECK(MF32(0xB4CFD8)==timestep);
    }
    after=clock_run(123,60,1);CHECK(fabs(after-124)<0.0001);
    /* Zero/negative steps and a first positive step are byte-identical;
     * positive callbacks preserve the same dt, sequence and two counters. */
    const float controls[]={0,-0.25f,1.0f/60.0f};
    for(unsigned i=0;i<3;++i) {
        reset();timestep=controls[i];make_callbacks=1;
        Cpu c=cpu();M32(c.esp+4)=self;memcpy(saved,G,MEMORY);Cpu native=c;
        carbon_orig_0076ADA0(&native);memcpy(expected,G,MEMORY);
        memcpy(G,saved,MEMORY);callbacks=allocations=0;f_0076ADA0(&c);
        CHECK(!memcmp(&c,&native,sizeof c));CHECK(!memcmp(G,expected,MEMORY));
        CHECK(callbacks==(i==2?19:0));
    }
}

static void model_setup(unsigned type) {
    reset();M32(RIDE)=type;M32(0)=0xBAD0BAD0;
    M32(STACK+4)=RIDE;
}
static void test_model(int retail_only) {
    model_setup(0);missing_type=0;Cpu c=cpu();M32(c.esp+4)=RIDE;
    carbon_orig_007E4A90(&c);CHECK(M32(0)==0);
    printf("K06 retail null writes=%u loaded type=%u\n",M32(0)==0,model_type);
    if(retail_only) { CHECK(M32(0)==0xBAD0BAD0);return; }
    model_setup(0);missing_type=0;c=cpu();M32(c.esp+4)=RIDE;f_007E4A90(&c);
    CHECK(M32(0)==0xBAD0BAD0);CHECK(model_type==1);CHECK(M32(RIDE)==0);
    CHECK(c.eax==0xCAFE);CHECK(c.esp==STACK+8);CHECK(probes==3);
    printf("K06 repaired null writes=%u loaded type=%u restored type=%u\n",M32(0)==0,model_type,M32(RIDE));
    /* Existing textures: compare every guest byte and the returned CPU. */
    model_setup(2);c=cpu();M32(c.esp+4)=RIDE;memcpy(saved,G,MEMORY);
    Cpu native=c;carbon_orig_007E4A90(&native);memcpy(expected,G,MEMORY);
    memcpy(G,saved,MEMORY);probes=0;f_007E4A90(&c);
    CHECK(model_type==2);CHECK(probes==2);CHECK(!memcmp(&c,&native,sizeof c));
    CHECK(!memcmp(G,expected,MEMORY));CHECK(M32(0)==0xBAD0BAD0);
    /* An incomplete stock installation has no usable replacement. */
    model_setup(0);missing_all=1;c=cpu();M32(c.esp+4)=RIDE;f_007E4A90(&c);
    CHECK(M32(0)==0);CHECK(M32(RIDE)==0);CHECK(model_type==0);
}

int main(int argc,char **argv) {
    if(argc!=3)return 2;
    G=calloc(1,MEMORY);image=malloc(MEMORY);saved=malloc(MEMORY);expected=malloc(MEMORY);
    if(!G||!image||!saved||!expected)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    if(fread(image,1,MEMORY,f)!=MEMORY)return 2;fclose(f);
    heap=heap_create("fixture",0x300000,0x400000,64);if(!heap)return 2;
    if(!strcmp(argv[2],"save"))test_save(0);
    else if(!strcmp(argv[2],"clock"))test_clock(0);
    else if(!strcmp(argv[2],"model"))test_model(0);
    else if(!strcmp(argv[2],"retail-save"))test_save(1);
    else if(!strcmp(argv[2],"retail-clock"))test_clock(1);
    else if(!strcmp(argv[2],"retail-model"))test_model(1);
    else return 2;
    printf("checks=%u failures=%u\n",checks,failures);return failures?1:0;
}
