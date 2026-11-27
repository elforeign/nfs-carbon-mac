"""Opt-in native player-AI handover on translated Carbon originals (no game).

Good: native handovers player0=1, player1=1 in split; single-player=1/0.
Original P1-only driver: player1=0 versus required 1, exit 1.
An explicit scripted results wait holds Return at 4; omitted guard gives 5 and fails.
Unset=0, paused=0, NIS=0.
Broken wrong-player and omitted-call variants: player0=0 versus required 1;
both exit 1, good exits 0. Pursuit Results (FePostStages.fng) is dismissed like race results:
returns 3 versus 2 without it (no-poststages variant, exit 1). Native control flag prevents repeated handovers.
Busted: returns 4 versus 3 without its name (no-busted variant, exit 1);
no key before 1.5 seconds; at most four attempts, spaced 1.5 seconds apart.
Ignored-first fixture: old code exits 1 (false departure); fixed code sends two
Returns, records one actual departure and then one resumed sample.
No-retry, premature-success and unbounded mutants each exit 1.
C3 ramp mock: target=45, full throttle/no brake, steer along the deck line
(dead zone added); Old-cap target=36 and omitted aim mutants exit 1.
Tick log repeats=0, new cumulative tick=1 with dispatch counter fixed at1;
the old per-dispatch counter logs0 new ticks and its mutant exits1.
Reverse approach at50 m is already on the deck line; a45 m entry fails this control.
A pre-bridge tick emits one trace; part-5
bridge-only diagnostics emit zero and fail. Duplicate ticks emit none.
C3 mock: left offset -> positive/right stick; right -> negative/left.
The sign-flipped follower exits 1; good exits 0. Arrival quits after 5 s;
unset/dependency guards preserve native AI.
Replay of the stopped forward run's logged states on the real first nine
route nodes/segments: target 35 m before the 8744 turn 23.8 (<=28; the
constant-36 mutant fails), stick change between two 1 m/s states 0.01
(<=0.2; the velocity-heading mutant, as the stopped run's +1.00 -> -1.00,
fails), reverse requested 3.0 s and run end 10.0 s after the car stops
progressing (no-reverse and no-end mutants fail). Log-only mode traces one
tick, leaves every control untouched and the pad off; its driving mutant fails.
Mode soak holds final results: returns remain 4; a missing guard returns 5
and fails. Releasing the hold permits return 5. Intermission policy is tested
through the real soak helper in private_soak_test.
Exit 3 without the pinned Carbon image and translated outputs.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRIVATE = HERE / 'private_runtime'
IMAGE_SHA = 'baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3'
BASELINES = {
    0x0065C2C0: '31b9d311ccb64f57e8b32dcb7f9c822b923b0e0151afe42e1004ade295a64d6f',
    0x0076E810: 'b9e8c48175029d55da34be2c2c5761ac6f63a4d47ee754f2f1e04536432cbf96',
    0x0076E740: '5ca45f1695d361d4e451c0f6854f7ac21b1c0b50b25e463abf2bf47bcfd8537b',
    0x004421B0: '055dee128f2cdff2e9ba02f7a7f3ebf2966dfe5bc23e1bd410de20394dd6166f',
    0x0060CB50: 'a784c47a6ffabe7b87c83d210f9cf5a6bd94712d56e73cf021bb2f872edeea19',
    0x0060C1B0: 'c8d7986a72e6c89c28af62f444c889f59cdb164cab00f87d649bfaf681034c0c',
}

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdarg.h>
#include <stdlib.h>
#include "carbon_autodrive.h"
uint8_t *G;
int diag_on = 1;
static HostFn present_callback;
static unsigned registrations, handovers[2], returns, samples, census_samples, departures;
static unsigned force_calls[2];
static uint64_t now = 1000000000ull;
static char line[1024];
static int hold_results;
static unsigned c3ticks;
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d %s (handovers=%u/%u)\n",__LINE__,#x,handovers[0],handovers[1]);exit(1);}}while(0)
uint64_t host_ticks(void) {return now;}
int pad_count(void) {return 1;}
int carbon_splitworld_rect(uint32_t v,uint32_t *r) {(void)v;(void)r;return 0;}
unsigned carbon_spliteffects_resources(void) {return 0;}
unsigned threads_handle_count(void) {return 12;}
void diag_event(const char *format,...) {
 va_list ap;va_start(ap,format);vsnprintf(line,sizeof line,format,ap);va_end(ap);
 if(strstr(line,"autodrive: dismissed"))++departures;
 if(strstr(line,"speed="))++samples;
 if(strstr(line,"c3tick:"))++c3ticks;
 if(strstr(line,"census:"))++census_samples;
}
void user32_autoreturn(void) {++returns;}
int carbon_soak_hold_results(void) {return hold_results;}
uint32_t host_fn(HostFn fn,const char *name) {
 ++registrations;
 CHECK(!strcmp(name,"autodrive prompts"));present_callback=fn;return 0xFF000014;
}
void abi_violation(Cpu *c,uint32_t fn,uint32_t b,uint32_t s,uint32_t d,uint32_t p,uint32_t sp) {
 (void)c;(void)b;(void)s;(void)d;(void)p;(void)sp;fprintf(stderr,"ABI %x\n",fn);abort();
}
void bad_jump(Cpu *c,uint32_t at) {(void)c;fprintf(stderr,"bad jump %x\n",at);abort();}
void untranslated(Cpu *c,uint32_t at) {bad_jump(c,at);}
void host_import(Cpu *c,uint32_t at) {bad_jump(c,at);}
void dispatch(Cpu *c,uint32_t target) {
 switch(target) {
 case 0x65C2C0:f_0065C2C0(c);break;
 case 0x76E810:f_0076E810(c);break;
 case 0x4421B0:f_004421B0(c);break;
 case 0xFF000003:c->eax=0;c->esp+=24;break;
 case 0xFF000001: case 0xFF000002: {
   unsigned player=target-0xFF000001;CHECK(c->ecx==0x9000+player*0x100);
   CHECK(arg(c,0)==1);++handovers[player];M8(c->ecx+0x10)=1;c->esp+=8;break;
 }
 default:bad_jump(c,target);
 }
}
uint32_t call_guest(Cpu *c,uint32_t target,int n,const uint32_t *args) {
 if(target==0x65C2C0)++force_calls[!!args[0]];
 uint32_t sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}
 c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,target);c->esp=sp;return c->eax;
}
#include "native.inc"
static Cpu cpu(void) {Cpu c={0};c.esp=0x200000;c.ecx=0x2004;c.cw=0x37F;return c;}
static void original(Cpu *c) {c->eax=0x2000;c->esp+=4;}
static void tick(void) {
 Cpu c=cpu();CHECK(present_callback);CHECK(present_callback(&c)==1);CHECK(c.esp==0x200018&&c.eax==0);
}
static void frame(void) {Cpu c=cpu();CHECK(present_callback);CHECK(present_callback(&c)==1);CHECK(c.esp==0x200018&&c.eax==0);}
static void setup(void) {
 G=calloc(1,0xC00000);CHECK(G);
 M32(0xAB0ABC)=0x16000;M32(0x16000)=0x17000;M32(0x17044)=0xFF000003;
 M32(0xA9FF64)=2;M32(0xA9FF5C)=0x1000;
 for(unsigned i=0;i<2;++i) {
   uint32_t player=0x2044+i*0x1000,sim=0x5000+i*0x1000;
   M32(0x1000+4*i)=player;M32(player)=0x4000;
   M32(0x4004)=0x76E810;M32(player-8)=sim;
   M32(sim)=0x4200;M32(0x4260)=0x6D7EA0;
   M32(sim+4)=0x7000+i*0x100;
   M32(0x7000+i*0x100)=0x8000+i*0x100;
   M32(0x7004+i*0x100)=0x8008+i*0x100;
   M32(0x8000+i*0x100)=0x4087C0;M32(0x8004+i*0x100)=0x9000+i*0x100;
   M32(0x9000+i*0x100)=0xA000+i*0x100;
   M32(0xA008+i*0x100)=0x4421B0;M32(0xA00C+i*0x100)=0xFF000001+i;
 }
 M32(0xA99BBC)=6;M32(0xB4CFE0)=0xB000;M32(0xB024)=3;
 M32(0x504C)=0xC000;M32(0xC000)=0xD000;M32(0xD020)=0x6C6FF0;
 M32(0xC030)=0xE000;M32(0xE000)=0xF000;MF32(0xF020)=50;
 M32(0xA98284)=0x300000;M32(0x306A08)=8;M32(0x300018)=123;M32(0x300064)=2;
 M32(0xAA26B4)=0x15000;M32(0xAA26BC)=1;M32(0x15000)=123;M32(0x15004)=0x5000;
}
/* Replay of the stopped forward run (c3route3-forward-pressure, c3tick lines)
 * on the real first nine route nodes and their native segments; the rest of
 * the mock route continues straight. */
static const float route_nodes[9][3]={
 {-3001.718018f,188.429855f,7827.218262f},{-3025.853027f,192.993240f,7779.934570f},
 {-3001.595947f,196.885590f,7721.664062f},{-2961.662354f,197.979248f,7668.274414f},
 {-2958.617188f,204.521240f,7623.935547f},{-2956.973633f,220.391754f,7536.725586f},
 {-2929.981689f,224.545776f,7497.180176f},{-2871.735352f,219.005722f,7458.549805f},
 {-2788.008301f,203.068665f,7406.539062f}};
/* Handles +12/+14, control directions at the end (+16) and start (+19). */
static const int route_segments[8][8]={
 {2311,2314,0,-8,126,-74,7,-102},{2815,2311,-63,-5,110,0,8,-126},
 {2338,2816,-50,-8,115,63,5,-110},{2916,2338,-4,-21,125,50,8,-115},
 {2873,2916,-27,-19,122,4,21,-125},{2526,2873,-93,1,85,27,19,-122},
 {3709,2526,-106,16,67,93,-1,-85},{4157,3709,-98,14,78,106,-16,-67}};
/* The bridge aim at 40 m/s on the lip axis: a point 30 m beyond the car on the
 * line through both deck centres, the 0.18 dead zone added, the term beyond
 * it held to 13 m/s2 sideways. */
static float deck_line_stick(int direction) {
 double ux=18.87/34.19,uz=-28.51/34.19;
 double t=(MF32(0xF010)+2636.45)*ux+(MF32(0xF018)-7214.21)*uz+direction*30.;
 float plain=carbon_c3drive_steer(-2636.45+t*ux-MF32(0xF010),7214.21+t*uz-MF32(0xF018),
                                  direction*.5383/hypot(.5383,.8428),-direction*.8428/hypot(.5383,.8428));
 return (float)copysign(fmin(1.,.18+fmin(fabs(plain),13./(.175*625.))),plain);
}
static double replay_target(void) {const char *t=strstr(line,"target=");return t?atof(t+7):-1;}
static void replay_state(double time,const double *p,const double *v) {
 MF32(0xF010)=p[0];MF32(0xF014)=p[1];MF32(0xF018)=p[2];
 MF32(0xF020)=v[0];MF32(0xF024)=v[1];MF32(0xF028)=v[2];
 MF32(0xB4CFD8)=time;M32(0xB4CFD4)++;carbon_c3drive_second=0;now+=500000000ull;
 CHECK(carbon_c3drive_frame(0x5000,now));
}
static void replay(void) {
 setenv("NFS_CARBON_C3_ROUTE","forward",1);
 for(unsigned i=0;i<52;++i) {
   uint32_t node=0x400000+32*carbon_c3drive_node(i,1);
   for(unsigned k=0;k<3;++k) MF32(node+4*k)=i<9?route_nodes[i][k]:route_nodes[8][k]+(i-8)*(route_nodes[8][k]-route_nodes[7][k]);
   M8(node+16)=0;
 }
 M32(0xB77ECC)=0x600000;
 for(unsigned i=0;i<8;++i) {
   uint32_t s=0x600000+22*i,node=0x400000+32*(8739+i);
   M16(s)=8739+i;M16(s+2)=8740+i;M16(s+12)=route_segments[i][0];M16(s+14)=route_segments[i][1];
   for(unsigned k=0;k<3;++k){M8(s+16+k)=(uint8_t)route_segments[i][2+k];M8(s+19+k)=(uint8_t)route_segments[i][5+k];}
   M8(node+16)=1;M16(node+18)=i;
 }
 carbon_c3drive_built=0;carbon_c3drive_straight=carbon_c3drive_landed=carbon_c3drive_airborne=0;
 carbon_c3drive_done=0;carbon_c3drive_reason=0;carbon_c3drive_arrived=0;
 MF32(0xF090)=MF32(0xF094)=MF32(0xF098)=0;
 /* t11.5, 35 m before the 8744 turn: the stopped run held 36 m/s and hit the wall at t13.0. */
 replay_state(11.5,(double[]){-2946.280762,221.080307,7540.231445},(double[]){10.388681,5.608220,-31.222559});
 double corner=replay_target();
 /* t16.0 and t16.5 at 1 m/s against that wall: velocity flipped the stopped run's
  * stick +1.00 -> -1.00. The facing is the pre-impact course (t12.5). */
 double course=hypot(-6.512753,-33.350063);
 MF32(0xF090)=-6.512753/course;MF32(0xF098)=-33.350063/course;
 replay_state(16.0,(double[]){-2942.925537,224.965942,7496.846680},(double[]){-0.538961,-0.037725,0.853507});
 float first=carbon_c3drive_lx;
 replay_state(16.5,(double[]){-2943.249756,224.947739,7497.201660},(double[]){-0.833317,-0.031629,0.243107});
 double flip=fabs(carbon_c3drive_lx-first);
 /* Blocked at the t14.0 state from t17: reverse, then the run ends itself. */
 double reverse=-1,end=-1;
 for(double t=17.;t<=40.&&end<0;t+=.5) {
   replay_state(t,(double[]){-2941.865479,225.007431,7495.968750},(double[]){0.456937,0.015330,-0.399789});
   if(reverse<0&&carbon_c3drive_lt==1&&carbon_c3drive_rt==0) reverse=t-16.;
   if(carbon_c3drive_done) end=t-16.;
 }
 printf("C3 REPLAY corner_target=%.1f (stopped run 36) low_speed_flip=%.2f (stopped run 2.00) reverse_after=%.1f s end_after=%.1f s\n",corner,flip,reverse,end);
 CHECK(corner>0&&corner<=28.);CHECK(flip<=.2);
 CHECK(reverse>0&&reverse<=3.5);CHECK(end>0&&end<=10.5);
 CHECK(carbon_c3drive_pad(0,&(float){0},&(float){0},&(float){0})==2);
 carbon_c3drive_done=0;carbon_c3drive_reason=0;
}
/* Log-only: traces, never writes a control, never takes the AI handover. */
static void log_only(void) {
 setenv("NFS_CARBON_C3_ROUTE","log",1);unsetenv("BOOT_PAD");unsetenv("BOOT_AUTODRIVE");
 carbon_c3drive_lx=carbon_c3drive_rt=carbon_c3drive_lt=.25f;carbon_c3drive_active=0;
 unsigned before=c3ticks;
 replay_state(20.,(double[]){-2635.271+10*.5383,212.,7214.961-10*.8428},(double[]){40*.5383,0,-40*.8428});
 CHECK(c3ticks==before+1&&strstr(line,"log_only=1")&&strstr(line,"s=10.0"));
 CHECK(carbon_c3drive_lx==.25f&&carbon_c3drive_rt==.25f&&carbon_c3drive_lt==.25f&&!carbon_c3drive_active);
 /* A different crossing must retain every physics tick: the old lip-only trace
  * drops this non-multiple-of-30 tick and cannot count airborne frames there. */
 MF32(0xF010)=1800;MF32(0xF018)=2800;M32(0xB4CFD4)++;
 carbon_c3drive_frame(0x5000,++now);CHECK(c3ticks==before+2);
 /* The optional impulse is inert without diagnostics, settling or four contacts;
  * the accepted launch changes only velocity, exactly once. */
 float launch[3]={1,2,3};MF32(0xB4CFD8)=3.f;
 setenv("NFS_TEST_C3_VELOCITY","20,1,-56",1);
 diag_on=0;carbon_c3drive_launch(0xF000,launch,4);CHECK(launch[0]==1);
 diag_on=1;carbon_c3drive_launch(0xF000,launch,0);CHECK(launch[0]==1);
 MF32(0xB4CFD8)=1.f;carbon_c3drive_launch(0xF000,launch,4);CHECK(launch[0]==1);
 MF32(0xB4CFD8)=3.f;setenv("NFS_TEST_C3_VELOCITY","nan,0,0",1);
 carbon_c3drive_launch(0xF000,launch,4);CHECK(launch[0]==1);
 setenv("NFS_TEST_C3_VELOCITY","20,1,-56",1);carbon_c3drive_launch(0xF000,launch,4);
 CHECK(launch[0]==20&&launch[1]==1&&launch[2]==-56&&MF32(0xF020)==20);
 launch[0]=7;carbon_c3drive_launch(0xF000,launch,4);CHECK(launch[0]==7);
 unsetenv("NFS_TEST_C3_VELOCITY");carbon_c3drive_launched=0;
 float lx=0,rt=0,lt=0;CHECK(!carbon_c3drive_pad(0,&lx,&rt,&lt));
 printf("C3 LOG-ONLY PASS controls=untouched pad=0 trace=1\n");
 setenv("BOOT_PAD","sim",1);setenv("BOOT_AUTODRIVE","1",1);
}
/* First Return is deliberately ignored; only the second lets the native
 * modal relinquish control. A third case never accepts any input. */
static void popup_retry(void) {
 M32(0x13020)=0;frame();
 strcpy(gptr(0x14000),"FeSmsMessage.fng");M32(0x13020)=1;M32(0xB024)=4;
 unsigned before=returns, left=departures, sampled=samples;
 frame();now+=1500000000ull;frame();CHECK(returns==before+1);
 CHECK(departures==left);CHECK(samples==sampled);
 now+=1499999999ull;frame();CHECK(returns==before+1);
 now+=1;frame();CHECK(returns==before+2);CHECK(departures==left);
 /* Model the accepted Return's native screen departure and resume separately. */
 M32(0x13020)=0;frame();CHECK(departures==left+1);CHECK(samples==sampled);
 M32(0xB024)=3;MF32(0xB4CFD8)+=.016666667f;M32(0xB4CFD4)++;
 MF32(0xF010)+=1;now+=1000000000ull;frame();CHECK(samples==sampled+1);
 CHECK(M32(0xB4CFD4)>0&&MF32(0xB4CFD8)>0);
 M32(0x13020)=1;M32(0xB024)=4;frame();before=returns;left=departures;
 for(unsigned i=0;i<10;++i){now+=1500000000ull;frame();}
 CHECK(returns==before+4&&departures==left);
 M32(0x13020)=0;frame();M32(0xB024)=3;
 printf("POPUP RETRY PASS ignored_first=1 attempts=2 departure=1 resumed_samples=1 bounded=4\n");
}
int main(void) {
 setenv("NFS_CARBON_CENSUS","1",1);
 setup();unsetenv("BOOT_AUTODRIVE");Cpu c=cpu();carbon_autodrive_construct(&c,original);
 CHECK(c.eax==0x2000&&c.esp==0x200004);
 CHECK(!registrations&&M32(0x17044)==0xFF000003);CHECK(!handovers[0]&&!handovers[1]);
 setenv("BOOT_AUTODRIVE","0",1);c=cpu();carbon_autodrive_construct(&c,original);CHECK(!registrations);
 setenv("BOOT_AUTODRIVE","1",1);c=cpu();carbon_autodrive_construct(&c,original);
 CHECK(registrations==1&&M32(0x17044)==0xFF000014);
 c=cpu();carbon_autodrive_construct(&c,original);CHECK(registrations==1);
 M32(0xA99BBC)=3;tick();CHECK(!handovers[0]&&!handovers[1]);
 M32(0xA99BBC)=6;M32(0xB024)=2;tick();CHECK(!handovers[0]);
 M32(0xB024)=3;M32(0xB4D964)=1;tick();CHECK(!handovers[0]);
 M32(0xB4D964)=0;M32(0xA9FF64)=0;tick();CHECK(!handovers[0]);
 M32(0xA9FF64)=2;tick();tick();tick();
 CHECK(handovers[0]==1&&handovers[1]==1);CHECK(samples==1&&census_samples==1);
 unsigned guest_calls=force_calls[1];M32(0xA9FF64)=1;tick();
 CHECK(force_calls[1]==guest_calls);M32(0xA9FF64)=2;
 diag_on=0;MF32(0xF010)=10;tick();CHECK(carbon_autodrive_distance==0&&samples==1&&census_samples==1);
 diag_on=1;MF32(0xF010)=0;
 for(unsigned i=0;i<100;++i){now+=20000000;MF32(0xF010)+=1;tick();}
 CHECK(handovers[0]==1&&handovers[1]==1);CHECK(samples==3&&census_samples==3);
 CHECK(fabs(carbon_autodrive_distance-100)<.001);CHECK(fabs(carbon_autodrive_top-50)<.001);
 CHECK(strstr(line,"lap=3 racers=8"));
 M32(0xA97A78)=0x11000;M32(0x11000)=0x12000;M32(0x120E4)=0x13000;
 M32(0x13020)=1;M32(0x1300C)=0x14000;strcpy(gptr(0x14000),"FePostRaceResults.fng");
 M32(0xB024)=2;frame();now+=1500000000;frame();CHECK(returns==1);frame();CHECK(returns==1);
 M32(0x13020)=0;frame();M32(0x13020)=1;frame();now+=1500000000;frame();CHECK(returns==2);
 strcpy(gptr(0x14000),"MainMenu.fng");now+=2000000000;frame();CHECK(returns==2);
 M32(0x13020)=0;frame();M32(0x13020)=1;strcpy(gptr(0x14000),"FePostStages.fng");frame();now+=1500000000;frame();CHECK(returns==3);
 M32(0x13020)=0;frame();M32(0x13020)=1;strcpy(gptr(0x14000),"FeBusted.fng");frame();CHECK(returns==3);
 now+=1499999999;frame();CHECK(returns==3);now+=1;frame();CHECK(returns==4);
 frame();CHECK(returns==4);
 M32(0x13020)=0;frame();hold_results=1;M32(0x13020)=1;
 strcpy(gptr(0x14000),"FePostRaceResults.fng");frame();now+=2000000000;frame();CHECK(returns==4);
 hold_results=0;setenv("BOOT_KEYS","seq:pkg:FePostRaceResults.fng,RETURN",1);
 frame();CHECK(returns==4);unsetenv("BOOT_KEYS");frame();CHECK(returns==5);
 printf("PRIVATE AUTODRIVE PASS handovers=%u/%u unset=0 paused=0 NIS=0 distance=%.0f samples=%u returns=%u\n",handovers[0],handovers[1],carbon_autodrive_distance,samples,returns);
 popup_retry();
 CHECK(carbon_c3drive_direction()==0);
 CHECK(carbon_c3drive_steer(2,10,0,1)>0);
 CHECK(carbon_c3drive_steer(-2,10,0,1)<0);
 setenv("NFS_CARBON_C3_ROUTE","forward",1);
 CHECK(carbon_c3drive_direction()==0);
 setenv("BOOT_PAD","sim",1);setenv("NFS_CARBON_SKIPFE","1",1);
 setenv("NFS_CARBON_SKIPFE_START","0,0,0",1);
 CHECK(carbon_c3drive_direction()==1);
 setenv("NFS_CARBON_C3_ROUTE","coast-forward",1);
 CHECK(carbon_c3drive_direction()==2&&carbon_c3drive_segments(2)==28);
 CHECK(carbon_c3drive_node(4,2)==1014&&carbon_c3drive_node(5,2)==8988);
 CHECK(carbon_c3drive_node(24,2)==9007&&carbon_c3drive_node(25,2)==5387);
 setenv("NFS_CARBON_C3_ROUTE","coast-reverse",1);
 CHECK(carbon_c3drive_direction()==-2&&carbon_c3drive_node(0,-2)==5384&&carbon_c3drive_node(28,-2)==1018);
 CHECK(carbon_c3drive_frame(0x5000,now)&&!carbon_c3drive_active);
 diag_on=0;CHECK(carbon_c3drive_direction()==0);diag_on=1;
 setenv("NFS_CARBON_C3_ROUTE","forward",1);
 M32(0xB77EC8)=0x400000;
 for(unsigned i=0;i<52;++i) {
   uint32_t node=0x400000+32*carbon_c3drive_node(i,1);
   MF32(node)=0;MF32(node+4)=0;MF32(node+8)=10*i;
 }
 /* Real forward start: before the bridge trace window, regardless of
  * the deliberately simple mock graph's position. */
 MF32(0xF010)=-3001.718;MF32(0xF014)=188.430;MF32(0xF018)=7827.218;
 MF32(0xF020)=-4.5463;MF32(0xF024)=0;MF32(0xF028)=-8.9068;
 unsigned route_ticks=c3ticks;
 M32(0xB4CFD4)=30;
 CHECK(carbon_c3drive_frame(0x5000,now));
 CHECK(c3ticks==route_ticks+1);
 carbon_c3drive_frame(0x5000,now);CHECK(c3ticks==route_ticks+1);
 MF32(0xF010)=-2;MF32(0xF014)=0;MF32(0xF018)=0;
 MF32(0xF020)=0;MF32(0xF028)=10;
 CHECK(carbon_c3drive_frame(0x5000,now));
 CHECK(carbon_c3drive_lx>0&&carbon_c3drive_rt>0);
 float lx=0,rt=0,lt=0;
 CHECK(!carbon_c3drive_pad(1,&lx,&rt,&lt));
 CHECK(carbon_c3drive_pad(0,&lx,&rt,&lt)==1&&lx>0&&rt>0);
 MF32(0xF010)=2;CHECK(carbon_c3drive_frame(0x5000,++now)&&carbon_c3drive_lx<0);
 MF32(0xF028)=10;
 MF32(0xF010)=0;MF32(0xF018)=510;
 CHECK(carbon_c3drive_frame(0x5000,++now));CHECK(carbon_c3drive_arrived&&!carbon_c3drive_done);
 CHECK(carbon_c3drive_rt==0&&carbon_c3drive_lt==1);
 now+=4999999999ull;carbon_c3drive_frame(0x5000,now);CHECK(!carbon_c3drive_done);
 carbon_c3drive_frame(0x5000,++now);CHECK(carbon_c3drive_done);
 CHECK(carbon_c3drive_pad(0,&lx,&rt,&lt)==2);
 carbon_c3drive_arrived=0;carbon_c3drive_done=0;carbon_c3drive_reason=0;
 setenv("NFS_CARBON_C3_ROUTE","reverse",1);CHECK(carbon_c3drive_direction()==-1);
 CHECK(carbon_c3drive_node(0,-1)==1534&&carbon_c3drive_node(51,-1)==8739);
 /* Real bridge frame, left of the axis on each ramp. Native mock graph
  * remains deliberately unrelated: look-ahead must not choose the target. */
 carbon_c3drive_arrived=0;carbon_c3drive_done=0;carbon_c3drive_reason=0;
 for(int direction=1;direction>=-1;direction-=2) {
   setenv("NFS_CARBON_C3_ROUTE",direction>0?"forward":"reverse",1);
   double along=direction>0?-20.:54.05;
   MF32(0xF010)=-2635.271+along*.5383+direction*2*.8428;
   MF32(0xF018)=7214.961-along*.8428+direction*2*.5383;
   MF32(0xF014)=210.;
   MF32(0xF020)=direction*40*.5383;MF32(0xF024)=0;
   MF32(0xF028)=-direction*40*.8428;
   MF32(0xB4CFD8)=1.;M32(0xB4CFDC)=1;M32(0xB4CFD4)++;
   carbon_c3drive_second=0;
   unsigned before=c3ticks;
   CHECK(carbon_c3drive_frame(0x5000,++now));
   CHECK(c3ticks==before+1&&strstr(line,"target=45.000"));
   float expected=deck_line_stick(direction);
   CHECK(carbon_c3drive_lx>0&&fabs(carbon_c3drive_lx-expected)<.00001);
   CHECK(carbon_c3drive_rt==1&&carbon_c3drive_lt==0);
   carbon_c3drive_frame(0x5000,++now);CHECK(c3ticks==before+1);
   M32(0xB4CFD4)++;carbon_c3drive_frame(0x5000,++now);CHECK(c3ticks==before+2);
 }
 unsigned logged=c3ticks;
 /* Reverse must align before the ramp, not first turn at its entry. */
 setenv("NFS_CARBON_C3_ROUTE","reverse",1);
 carbon_c3drive_straight=carbon_c3drive_landed=carbon_c3drive_airborne=0;
 double along=84.05;
 MF32(0xF010)=-2635.271+along*.5383-2*.8428;
 MF32(0xF018)=7214.961-along*.8428-2*.5383;
 MF32(0xF020)=-40*.5383;MF32(0xF028)=40*.8428;
 carbon_c3drive_frame(0x5000,++now);
 float approach=deck_line_stick(-1);
 CHECK(carbon_c3drive_straight&&fabs(carbon_c3drive_lx-approach)<.00001);
 diag_on=0;M32(0xB4CFD4)++;carbon_c3drive_frame(0x5000,++now);CHECK(c3ticks==logged);
 diag_on=1;
 unsetenv("NFS_CARBON_C3_ROUTE");CHECK(!carbon_c3drive_pad(0,&lx,&rt,&lt));
 M32(0xB4CFD4)++;CHECK(!carbon_c3drive_frame(0x5000,++now)&&c3ticks==logged);
 replay();log_only();
 printf("C3 DRIVER PASS left=right right=left arrival=5s guards=PASS\n");
 free(G);return 0;
}
'''


def run(args, expected=0):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    assert result.returncode == expected, (args[:3], result.returncode,
                                          result.stdout[-1000:], result.stderr[-3500:])
    return result


def main():
    base = HERE / 'out/carbon-base'
    if not all((base / p).is_file() for p in ('image.json', 'table.c', 'funcs.h', 'NFSC.a')):
        print('SKIP: private_autodrive_test needs Carbon outputs')
        return 3
    image = json.loads((base / 'image.json').read_text())
    if not Path(image['exe']).is_file():
        print('SKIP: private_autodrive_test needs the pinned image')
        return 3
    sys.path.insert(0, str(HERE))
    import build_all
    import private_hooks
    import private_hooks_test
    import recomp
    pe = recomp.PE(image['exe'], expected_sha256=IMAGE_SHA)
    # The actual IHumanAI slots used by the retained script command.
    assert pe.read(0x009C500C, 8) == bytes.fromhex('b0 21 44 00 b0 94 41 00')
    starts = [int(v.strip().removesuffix('u'), 16) for v in re.search(
        r'guest_func_addr\[\] = \{([^}]+)', (base / 'table.c').read_text())[1].split(',')]
    functions = [(a, starts[i+1] if i+1 < len(starts) else a+16, 'fixture')
                 for i, a in enumerate(starts)]
    hooks = private_hooks.load_registry(pe, functions)
    assert hooks[0x76FB20]['provider'] == 'carbon_autodrive_construct'
    native = []
    for address, digest in BASELINES.items():
        source = (base / f'NFSC_{starts.index(address)//build_all.CHUNK:02d}.c').read_text()
        name = f'f_{address:08X}'
        body = private_hooks_test.body(source, name)
        assert hashlib.sha256(body.encode()).hexdigest() == digest, hex(address)
        native.append(body)
    feature = json.loads((PRIVATE / 'features/autodrive.json').read_text())
    for name in feature['sources']:
        canonical = PRIVATE / feature['staged_sources'][name]
        assert feature['bindings'][name]['sha256'] == hashlib.sha256(canonical.read_bytes()).hexdigest()
    source = (PRIVATE / 'carbon_autodrive.h').read_text()
    with tempfile.TemporaryDirectory(prefix='private-autodrive-') as directory:
        tmp = Path(directory)
        (tmp / 'native.inc').write_text('\n\n'.join(native))
        (tmp / 'fixture.c').write_text(HARNESS)
        follower = (PRIVATE / 'carbon_c3drive.h').read_text()
        (tmp / 'carbon_c3drive.h').write_text(follower)
        variants = {
            'good': source,
            'no-retry': source.replace('attempts >= 4', 'attempts >= 1'),
            'unbounded': source.replace('attempts >= 4', 'attempts >= 100'),
            'premature-success': source.replace('++attempts;', '++attempts; if (diag_on) diag_event("autodrive: dismissed %s", text);'),
            'wrong-player': source.replace('uint32_t args[] = {0};', 'uint32_t args[] = {1};'),
            'no-busted': source.replace(' || !strcmp(text, "FeBusted.fng")', ''),
            'no-poststages': source.replace(' || !strcmp(text, "FePostStages.fng")', ''),
            'no-soak-hold': source.replace('    if (!strcmp(text, "FePostRaceResults.fng") && carbon_soak_hold_results()) return;\n', ''),
            'omitted-call': source.replace('call_guest(&drive, 0x0065C2C0u, 1, args);', '(void)drive; (void)args;'),
            'original-p1-only': source.replace('if (M32(0x00A9FF64u) == 2)', 'if (0)'),
            'no-script-results-hold': source.replace('    if (!strcmp(text, "FePostRaceResults.fng") && keys && strstr(keys, "pkg:FePostRaceResults.fng")) return;\n', ''),
        }
        assert all(text != source for name, text in variants.items() if name != 'good')
        for name, text in variants.items():
            (tmp / 'carbon_autodrive.h').write_text(text)
            binary = tmp / name
            run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                 '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            result = run([binary], 0 if name == 'good' else 1)
            print(f'{name}: exit={result.returncode} {(result.stdout or result.stderr).strip()[:400]}')
        (tmp / 'carbon_autodrive.h').write_text(source)
        mutant = follower.replace('right = hz*dx-hx*dz;', 'right = hx*dz-hz*dx;')
        assert mutant != follower
        (tmp / 'carbon_c3drive.h').write_text(mutant)
        binary = tmp / 'c3-sign'
        run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
             '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
        result = run([binary],1)
        print('c3-sign: exit=1 '+result.stderr.strip()[:200])
        old_cap = follower.replace('if (bridge) target=45.;', 'if (bridge) target=36.;')
        assert old_cap != follower
        (tmp / 'carbon_c3drive.h').write_text(old_cap)
        binary = tmp / 'c3-old-cap'
        run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
             '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
        result = run([binary],1)
        print('c3-old-cap: exit=1 '+result.stderr.strip()[:200])
        no_aim = follower.replace('int lip_aim=carbon_c3drive_straight && !carbon_c3drive_landed;',
                                  'int lip_aim=0;')
        assert no_aim != follower
        (tmp / 'carbon_c3drive.h').write_text(no_aim)
        binary = tmp / 'c3-no-lip-aim'
        run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
             '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
        result = run([binary],1)
        print('c3-no-lip-aim: exit=1 '+result.stderr.strip()[:200])
        dispatch_tick = follower.replace('tick=M32(0x00B4CFD4u)', 'tick=M32(0x00B4CFDCu)')
        assert dispatch_tick != follower
        (tmp / 'carbon_c3drive.h').write_text(dispatch_tick)
        binary = tmp / 'c3-dispatch-tick'
        run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
             '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
        result = run([binary],1)
        print('c3-dispatch-tick: exit=1 '+result.stderr.strip()[:200])
        late_aim = follower.replace('progress>=-130. && progress<=0.', 'progress>=-45. && progress<=0.')
        assert late_aim != follower
        (tmp / 'carbon_c3drive.h').write_text(late_aim)
        binary = tmp / 'c3-late-reverse-aim'
        run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
             '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
        result = run([binary],1)
        print('c3-late-reverse-aim: exit=1 '+result.stderr.strip()[:200])
        corrections = {
            'c3-part5-route-trace': follower.replace('bridge_trace || tick%30==0', 'bridge_trace'),
            # Each restores one behaviour of the stopped part-6 follower.
            'c3-constant-36': follower.replace('double target=carbon_c3drive_vmax[here];', 'double target=36.;'),
            'c3-velocity-heading': follower.replace('if (planar<8. &&', 'if (planar<0. &&'),
            'c3-no-reverse': follower.replace('speed<4. &&', 'speed<0. &&'),
            'c3-no-end': follower.replace('>=10.) carbon_c3drive_reason', '>=1e9) carbon_c3drive_reason'),
            'c3-log-drives': follower.replace('    if (logging) {', '    if (0) {'),
        }
        for name, text in corrections.items():
            assert text != follower
            (tmp / 'carbon_c3drive.h').write_text(text)
            binary = tmp / name
            run(['clang', '-O1', '-g', '-DRECOMP_ABICHECK', '-fsanitize=address,undefined',
                 '-I', HERE, '-I', PRIVATE, '-I', base, '-I', ROOT / 'runtime', tmp / 'fixture.c', '-o', binary])
            result = run([binary], 1)
            print(name+': exit=1 '+result.stderr.strip()[:200])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
