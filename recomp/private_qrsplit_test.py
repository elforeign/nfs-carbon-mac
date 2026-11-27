"""Carbon native Quick Race split entry, ports, join/cancel and player factory.

Good: 142/142 checks. One FE port fails 7/142; the native 1 KiB split car
budget fails 2/142. Press edges, held-button suppression, release/rejoin,
single-controller allocation and native budget reductions execute C below.
The unhooked translated menu is the original failing control. Boundaries fake
allocation, FE presentation and the attribute service; native state transitions,
port assignment, join input, mode selection and local-player creation execute C.
Exit 3 without the private image/translated output. No devices or emulation.
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
NATIVE = (0x84B370, 0x858480, 0x867F00, 0x854300, 0x8676C0,
          0x848540, 0x848590, 0x8485E0, 0x83CAF0, 0x5723A0,
          0x572C70, 0x572C90, 0x579200, 0x579C10, 0x6999C0,
          0x7655D0, 0x4A5A10, 0x4A5D20, 0x844140,
          0x5720E0, 0x5F25F0, 0x5F0690, 0x5E9DC0, 0x600C90,
          0x572040, 0x5E9E40, 0x5FD770, 0x5E9EF0,
          0x680310, 0x680350, 0x680320, 0x678900, 0x87EAC0, 0x6BBDF0)
HOOKS = {0x84B370: 'carbon_qrsplit_label', 0x858480: 'carbon_qrsplit_choice',
         0x867F00: 'carbon_qrsplit_accept', 0x854300: 'carbon_qrsplit_transition',
         0x845DD0: 'carbon_qrsplit_destroy', 0x6BBDF0: 'carbon_qrsplit_memory'}

BASELINES = {
    0x6BBDF0: 'e3b6085557f7baf211f57184e5a1708928dd8891f3a2c0aa2bf31b62f0dc9303',
    0x680310: '39a30e1db6cc3d3d1f0c96de3195ff1949823c2416eabed63818d8526cedaf18',
    0x680350: 'e58bd47287570f6526952af01e3bc5a5b1bd88599bb770eb4ab73c4eba6ec2ad',
    0x680320: '168098b85dd357f6220431c355059ca117cd955a50c714f55c8eba219755d2c2',
    0x678900: '40385b9f5501dc3ae743401d8fa07c87838e7eb09a67f55e93a76414ad9799f7',
    0x87EAC0: '613c584ed1cb82b7014a6eca36763dae6aec8f78e3feb2d21d5d02ee0a30312c',

    0x5720E0: 'ebc8241931a84379b8ec1c8664a1b5c8151dbfa6517011f6955d299dcb5c4bb5',
    0x5F25F0: '82feec7f37b794417e30933effdb410162f170b0304e764a25ce2e46861a8131',
    0x5F0690: '067fa9794f912016cb24d085d044c99d95a9a2bd33b1777b2393cde89d2960fc',
    0x5E9DC0: '5f81bae5649dc1ea7af6b506b9f751fcaa2bb3e83f0832054fb887a5b0aaa2b7',
    0x600C90: 'e4bb91ecff47d42e138dd3878082699c7cf6ca6e5e0772206b9bdc54e12aaf76',
    0x572040: '387b31760c907d863ef186bd0aeaeba86ac51b4e32e0c79c54f437cbac30dccf',
    0x5E9E40: '51168af6f7b943a3892fd02c90c4de07c69de7d861e86938814d29debda23743',
    0x5FD770: '37c849237b6b5622a46a95639044a768a64e2046c83d553b91ff68966aa3a56c',
    0x5E9EF0: '1358ebe2bc13039a0a5a86a96561b86f7ad41a82f2b31786c51b504c99157f18',

    0x844140: '002a5f3b96e252818e5f6b7349308004b8d6a01f86d47628aa35ca441a4b092a',
    0x84B370: 'b5747a2d60dc6d0688a38a69146ff2a4ba40c85afbcfaabe2d6d2d60158e9490',
    0x858480: '5f4cc1650843c3e76f00ec3a0b9c3ccdb4d6bf6638f732d050f16f3c23b959c1',
    0x867F00: 'c8eaeeb6ea7c5fc21305f279fb035cca54cdc1f5a938b1880d1d9a950d6a6caa',
    0x854300: '07f53162015a2e0918152809318b52a323b729dc36707428631816e0f8d1b29b',
    0x8676C0: '2e85535e2f5d45cf59aa42324c525e75d5bc67e86ef4eb530a8fb9d0bc43f6be',
    0x848540: '917a214dde91592fcd91de988928dc5d0c3c31516c0fae399fa58a8278114540',
    0x848590: '3123666216f971017773dccf5a919aad4d2ea7a507f27f732218a5908d3ff224',
    0x8485E0: 'e3b5f11bad284cb476022c4aa9631d7666c12a1d3131e2af0e46188f490a385f',
    0x83CAF0: '2ab712c53d7cd44a69d8ceda1ad987a9df7aa730e445746d01470d0538a31456',
    0x5723A0: '8638ac6532b3f971b81c15ab200a7d4be2c2d3f0d43a19cd42a653db47a955c7',
    0x572C70: '4833bdcc3b7237077d7b738a5ffaf98001385764c9a205ee5b2f23ede282673b',
    0x572C90: 'bbf63006c600c26d1dc5e839929f35a8d7a7f73be607a224500d1074c870cdc7',
    0x579200: '1dc12a0185e5fcc1343a98d9e380d93d566039c5d44afa6fb5ff054d4d7da182',
    0x579C10: '8e54133e1c4303d0e09ddfe966825519a397b8778d38cec48f7dd07ef2adc0bf',
    0x6999C0: '590a5430b529d60b6a577d5d818e0470ce7e00994fd7c3470c31e17d8de3aced',
    0x7655D0: 'bb1cfdbe4aefd5f607743fad7f0b14cd5d1ee376651539d9f6435ac915902260',
    0x4A5A10: 'bac66bfbfcd564333a9ad3835e04d4d97c320113b9abc8f245951766434e1ff5',
    0x4A5D20: '1489692bcd6f3327415bc5b020c7117f9772e4a1ee5f1d348ae42420520e2f19',
}

HARNESS = r'''
#include "funcs.h"
#include "host.h"
#include <stdlib.h>
uint8_t *G;
int diag_on;
static unsigned checks, failures, labels, starts, players, port_calls, allocs, fail_alloc;
static unsigned other_choice, other_sets;
static unsigned join_messages, join_mask, sampled;
static unsigned allocated_budget;
static unsigned ports[2], hud[2], index_[2], viewport[2], cars[2], car_context;
static int pads=2, split;
enum { STACK=0x200000, DB=0x300000, PORTS=0x310000, PROFILE=0x320000,
       OPTIONS=0x360000, QR=0x370000, ROW=0x380000, FE=0x390000 };
#define CHECK(x) do {++checks;if(!(x)){if(failures<12)fprintf(stderr,"FAIL %d %s\n",__LINE__,#x);++failures;}}while(0)
int pad_count(void){return pads;}
uint64_t host_ticks(void){return 1000000000ull;}
int pad_read_n(int n,PadState *s){(void)n;memset(s,0,sizeof *s);return 0;}
void diag_event(const char *f,...){(void)f;}
void bad_jump(Cpu *c,uint32_t a){(void)c;fprintf(stderr,"bad jump %08X\n",a);abort();}
#include "native.inc"
#include "carbon_qrsplit.c"
#include "carbon_padguest.c"
static Cpu cpu(uint32_t self){Cpu c={0};c.ecx=self;c.esp=STACK;c.fs_base=0x210000;M32(STACK)=0xFEEDF00D;return c;}
static unsigned mode(void){return M8(PROFILE+0x2B0D3);}
static void original_destroy(Cpu *c){c->esp+=4;}
static void transition(uint32_t state){Cpu c=cpu(QR);M32(QR+4)=state;carbon_qrsplit_transition(&c,native_00854300);CHECK(c.esp==STACK+4);}
static void reset(void){
    memset(G,0,0xC00000);init_image();pads=2;split=starts=players=labels=port_calls=allocs=fail_alloc=0;
    other_choice=other_sets=0;
    memset(hud,0,sizeof hud);memset(ports,0,sizeof ports);
    cars[0]=100;cars[1]=200;
    M32(0xA97A7C)=DB;M32(DB+0xCC)=PORTS;M8(PORTS)=0;M8(PORTS+1)=255;M32(DB+0xC8)=~0u;
    M32(0xA97814)=FE;M32(0xBBAA54)=OPTIONS;M32(0xBBAAFC)=QR;M32(0xA99BBC)=3;
    M32(QR)=0x9F8428;M32(QR+4)=2;M32(QR+0xD0)=0;M32(QR+0xCC)=123;
    M32(OPTIONS+0x164)=0;M32(ROW+0x74)=0x13E4;M8(ROW+0x64)=1;M32(ROW+0x1C)=0x420000;
    M32(ROW)=0x9F96A4;M32(0xA97A78)=0x410000;
    M32(0xB4D978)=0x430000;M32(0x430000)=1;M32(0x430004)=0x11111111;M32(0x430008)=0x430010;
    M32(0x430010)=2;M32(0x430014)=0x11111112;
}
static void choose(int direction){Cpu c=cpu(ROW);M32(STACK+4)=0;M32(STACK+8)=direction<0?0x9120409E:0xB5971BF1;carbon_qrsplit_choice(&c,native_00858480);CHECK(c.esp==STACK+12);}
static void accept(void){Cpu c=cpu(QR);carbon_qrsplit_accept(&c,native_00867F00);CHECK(c.esp==STACK+4);}
static void result(unsigned state,unsigned value){M32(QR+4)=state;Cpu c=cpu(QR);M32(STACK+4)=value;native_008676C0(&c);CHECK(c.esp==STACK+8);}
static void join(void){
    uint32_t screen=0x450000;M32(0xBBAA58)=screen;M32(screen+0x28)=1;
    Cpu c=cpu(screen);M32(STACK+4)=0xB5AF2461;M32(STACK+8)=0;M32(STACK+12)=2;M32(STACK+16)=0;
    native_0083CAF0(&c);CHECK(c.esp==STACK+20);
}
/* The real FE allocator and poller must sample port 1 before the retained
 * package edge detector can deliver START with mask 2 to the join callback. */
static void poll_join(unsigned value){
    uint32_t q=carbon_padguest_second;
    M32(q)=1;M32(q+8)=0;M32(q+12)=50;M32(q+16)=0x34;MF32(q+24)=(float)value;
    Cpu c=cpu(FE);carbon_padguest_events(&c,original_destroy);CHECK(c.esp==STACK+4);
    CHECK(M32(0xA5E048+28*7)==value); /* queue event 34 -> START bit 40 */
    c=cpu(0x510000);M32(STACK+4)=16;M32(STACK+8)=0;native_00600C90(&c);CHECK(c.esp==STACK+12);
}
static void input_proof(void){
    reset();join_messages=join_mask=sampled=0;
    carbon_padguest_fe=FE;carbon_padguest_second=0x580000;M8(0x58028C)=1;
    M32(0xA97A70)=0x570000;M32(0x570000)=0x9D0610;
    Cpu c=cpu(0x410000);native_005720E0(&c);CHECK(c.esp==STACK+4);
    CHECK(M32(0x510000+0xD0)==(unsigned)pads);
    uint32_t package=0x550000,handler=0x560000;
    M32(0x510000+0xE0)=package;M32(package+0x20)=3;M8(package+0x28)=1;
    M32(package+0x5C)=handler;M32(handler+0xC)=0xB5AF2461;
    M32(0xBBAA58)=0x450000;M32(0x450000+0x28)=1;
    poll_join(0);CHECK(!join_messages);
    poll_join(1);CHECK(sampled==3);CHECK(join_messages==1&&join_mask==2);
    CHECK(M8(PORTS)==0&&M8(PORTS+1)==1);
    poll_join(1);CHECK(join_messages==1); /* held START is not another accept */
    poll_join(0);CHECK(join_messages==1);
    M8(PORTS+1)=255;poll_join(1);CHECK(join_messages==2&&M8(PORTS+1)==1);
    /* Single-controller allocation and unrelated resizes keep native counts. */
    reset();pads=1;c=cpu(0x410000);native_005720E0(&c);CHECK(M32(0x510000+0xD0)==1);
    pads=2;c=cpu(0x510000);M32(STACK+4)=1;carbon_padguest_ports(&c,native_005F25F0);CHECK(M32(0x510000+0xD0)==1);
    c=cpu(0x510000);M32(STACK)=0x572144;M32(STACK+4)=0;carbon_padguest_ports(&c,native_005F25F0);CHECK(!M32(0x510000+0xD0));
}
static void memory_proof(void){
    for(unsigned controllers=1;controllers<=2;++controllers)for(unsigned two=0;two<2;++two){
        reset();pads=controllers;split=two;allocated_budget=0;
        Cpu c=cpu(0x590000);carbon_qrsplit_memory(&c,native_006BBDF0);CHECK(c.esp==STACK+4);
        CHECK(allocated_budget==(two&&controllers==1?1024u:65000u*1024));
        CHECK(M32(0xA62C4C)==1); /* restore the image field after native initialization */
    }
    reset();split=1;M32(0xA9E668)=1;M32(0xB69C10)=1;M32(0xA62C4C)=2;
    Cpu c=cpu(0x590000);carbon_qrsplit_memory(&c,native_006BBDF0);
    CHECK(allocated_budget==(65000u*1024-0x40000)/2);CHECK(M32(0xA62C4C)==2);
}
static void factory(unsigned count){Cpu c=cpu(0);native_006999C0(&c);M32(0xB4D854)=c.eax&255;CHECK((c.eax&255)==(count==2));players=0;c=cpu(0);native_007655D0(&c);CHECK(players==count);if(count==2){CHECK(ports[0]==0&&ports[1]==1);CHECK(index_[0]==0&&index_[1]==1);CHECK(viewport[0]==1&&viewport[1]==2);CHECK(hud[0]==3&&hud[1]==4);}else CHECK(ports[0]==0&&hud[0]==1);}
static void select_car(unsigned player,unsigned id){unsigned self=0x480000;M32(self)=0x490000;M32(0x490114)=0x59AFC0;M32(0x49010C)=0x59AFA0;M32(self+4)=player?3:1;M32(self+8)=player?2:1;M32(self+0xD0)=0x4A0000;M32(0x4A0008)=id;unsigned other=cars[1-player];Cpu c=cpu(self);native_00844140(&c);CHECK(c.esp==STACK+4);CHECK(cars[player]==id);CHECK(cars[1-player]==other);CHECK(M32(self+4)==(player?4:2));}
static void proof(void){
    reset();choose(1);CHECK(mode()==1);choose(1);CHECK(mode()==2);Cpu c=cpu(ROW);carbon_qrsplit_label(&c,native_0084B370);CHECK(labels>=1);CHECK(c.esp==STACK+4);
    choose(1);CHECK(mode()==0);choose(-1);CHECK(mode()==2);accept();CHECK(split==1);CHECK(M32(QR+4)==8);CHECK(M8(PORTS)==0);CHECK(M8(PORTS+1)==255);
    if(M32(QR+4)!=8){factory(2);reset();split=1;M8(PORTS+1)=1;M32(DB+0xC4)=1;transition(2);CHECK(!split);CHECK(M8(PORTS+1)==255);CHECK(!M32(DB+0xC4));return;}
    select_car(0,321);
    result(8,6);CHECK(M32(QR+4)==10);CHECK(M32(DB+0xC4)==1);CHECK(M8(PORTS+1)==255);
    join();CHECK(M8(PORTS)==0&&M8(PORTS+1)==1);CHECK(port_calls>=3);
    result(10,1);CHECK(M32(QR+4)==11);CHECK(car_context==2);
    select_car(1,654);CHECK(cars[0]==321&&cars[1]==654);
    result(11,6);CHECK(M32(QR+4)==13);CHECK(starts==1);factory(2);
    /* Native cancellation from the first car list returns to options. */
    reset();M8(PROFILE+0x2B0D3)=2;accept();result(8,7);CHECK(M32(QR+4)==2);CHECK(!split);CHECK(M8(PORTS)==0&&M8(PORTS+1)==255);CHECK(!M32(DB+0xC4));factory(1);
    /* Return/rejoin, including an already assigned P2. */
    accept();result(8,6);join();result(10,0);CHECK(M8(PORTS+1)==255);transition(2);CHECK(!split);accept();result(8,6);join();CHECK(M8(PORTS+1)==1);
    /* P2 cancelling its car list releases ownership before the next join. */
    result(10,1);result(11,7);CHECK(M32(QR+4)==8);CHECK(M8(PORTS+1)==255);CHECK(!M32(DB+0xC4));CHECK(split);
    result(8,6);join();CHECK(M8(PORTS+1)==1&&M32(DB+0xC4)==1);
    /* Starting without an independent second owner must return to options. */
    M8(PORTS+1)=0;transition(13);CHECK(M32(QR+4)==2);CHECK(!split);CHECK(!starts);
    /* Allocation failure must not leave an armed split race. */
    reset();M8(PROFILE+0x2B0D3)=2;fail_alloc=1;accept();CHECK(!split);CHECK(M8(PORTS+1)==255);CHECK(M32(QR+4)==2);
    /* The ordinary one-controller choice executes its retained code. */
    reset();pads=1;choose(1);CHECK(mode()==1);choose(1);CHECK(mode()==0);M8(PROFILE+0x2B0D3)=1;accept();CHECK(!split);CHECK(M32(QR+4)==3);
    reset();pads=1;M8(PROFILE+0x2B0D3)=2;c=cpu(ROW);carbon_qrsplit_label(&c,native_0084B370);CHECK(mode()==0);CHECK(!split);
    reset();split=1;M8(PORTS+1)=1;M32(DB+0xC4)=1;M32(QR+4)=10;c=cpu(QR);carbon_qrsplit_destroy(&c,original_destroy);CHECK(!split);CHECK(M8(PORTS+1)==255);CHECK(!M32(DB+0xC4));CHECK(c.esp==STACK+4);
    reset();split=1;M8(PORTS+1)=1;M32(QR+4)=13;c=cpu(QR);carbon_qrsplit_destroy(&c,original_destroy);CHECK(split&&M8(PORTS+1)==1);CHECK(c.esp==STACK+4);
    /* The increment callback is shared by five native option classes. */
    reset();M32(ROW+0x74)=0x13E8;choose(1);CHECK(other_choice==1&&other_sets==1);CHECK(mode()==0);
}
void dispatch(Cpu *c,uint32_t a){
    switch(a){
    case 0x7990C0:c->eax=0;c->esp+=4;return;
    case 0x4750C0:case 0x4750F0:case 0x6B2300:case 0x557F70:c->eax=0;c->esp+=4;return;
    case 0x470FC0:case 0x557F80:c->eax=0;c->esp+=4;return;
    case 0x477230:c->eax=0x5D0000;c->esp+=4;return;
    case 0x6B48B0:c->eax=0;c->esp+=4;return;
    case 0x7FC0E0:case 0x557FF0:case 0x6BB820:c->esp+=4;return;
    case 0x557F90:c->esp+=4;return;
    case 0x7E4910:allocated_budget=arg(c,0);M32(0xB77084)=allocated_budget;c->esp+=8;return;
    case 0x7B1810:c->esp+=12;return;
    case 0x561590:c->eax=0;c->esp+=4;return;
    case 0x5F25F0:carbon_padguest_ports(c,native_005F25F0);return;
    case 0x403A60:{unsigned out=arg(c,0),size=arg(c,1),count=arg(c,2),ctor=arg(c,3);for(unsigned i=0;i<count;++i){Cpu q=*c;q.ecx=out+i*size;q.esp-=128;call_guest(&q,ctor,0,NULL);}c->esp+=20;return;}
    case 0x6A15A0:c->esp+=4;return;
    case 0x5FC930:M8(c->ecx)=1;M32(c->ecx+0xE0)=0;c->eax=c->ecx;c->esp+=4;return;
    case 0x5F69D0:case 0x5FCAA0:case 0x6007C0:c->esp+=4;return;
    case 0x5EBDE0:c->esp+=8;return;
    case 0x572050:memset(G+arg(c,0),0,8);c->esp+=8;return;
    case 0x5EB7E0:c->esp+=12;return;
    case 0x5F2960:{unsigned message=arg(c,0),mask=arg(c,4);if(message==0xB5AF2461&&arg(c,3)==0xFFFFFFFDu){++join_messages;join_mask=mask;Cpu q=*c;q.ecx=M32(0xBBAA58);q.esp-=128;uint32_t args[]={message,0,mask,0};call_guest(&q,0x83CAF0,4,args);}c->esp+=24;return;}
    case 0x5F48F0:case 0x5F6F90:c->esp+=8;return;
    case 0x572040:sampled|=1u<<(arg(c,0)&255);native_00572040(c);return;
    case 0x678900:native_00678900(c);return;
    case 0x4A0490:{unsigned property=arg(c,0),out=arg(c,1);if(property==0x13E4){Cpu q=*c;q.esp-=128;uint32_t args[]={out,arg(c,2)};call_guest(&q,0x4A5A10,2,args);}else M32(out)=property==0xBC7?split:0;c->eax=1;c->esp+=24;return;}
    case 0x4A04E0:{unsigned p=arg(c,0);if(p==0xBC7)split=arg(c,1);else if(p==7000){CHECK(arg(c,2)<2);cars[arg(c,2)]=arg(c,1);}else if(p==0x13E4){Cpu q=*c;q.esp-=128;uint32_t args[]={arg(c,1),arg(c,2)};call_guest(&q,0x4A5D20,2,args);}c->eax=1;c->esp+=24;return;}
    case 0x4A0530:{if(arg(c,0)!=0x13E4){CHECK(arg(c,0)==0x13E8);++other_sets;other_choice+=arg(c,1);}else{int v=(int)mode()+(int)arg(c,1);M8(PROFILE+0x2B0D3)=v<0?1:v>1?0:v;}c->eax=1;c->esp+=24;return;}
    case 0x572B90:c->eax=PROFILE;c->esp+=8;return;
    case 0x84B6F0:c->esp+=4;return;
    case 0x583A90:if(arg(c,1)==0x37CE1D36)++labels;c->esp+=4;return;
    case 0x84B370:carbon_qrsplit_label(c,native_0084B370);return;
    case 0x854300:carbon_qrsplit_transition(c,native_00854300);return;
    case 0x59AFC0:case 0x59AFA0:c->esp+=4;return;
    case 0x5828D0:case 0x576E60:c->esp+=8;return;
    case 0x6A1560:++allocs;c->eax=fail_alloc?0:0x500000+allocs*0x10000;c->esp+=4;return;
    case 0x862090:car_context=arg(c,1);M32(c->ecx)=0x9FB350;c->eax=c->ecx;c->esp+=16;return;
    case 0x59C130:c->eax=c->ecx;c->esp+=20;return;
    case 0x863000:M32(QR+4)=5;c->esp+=8;return;
    case 0x59ABD0:c->eax=c->ecx;c->esp+=8;return;
    case 0x5A52B0:case 0x589060:{unsigned child=arg(c,0),state=arg(c,1),parent=c->ecx;M32(parent+0xB0)=child;M32(parent+4)=state;Cpu q=*c;q.esp-=128;M32(q.esp)=0xFEEDF00D;carbon_qrsplit_transition(&q,native_00854300);if(child&&M32(child)==0x9F9320){q=*c;q.ecx=child;q.esp-=128;native_00848590(&q);}c->esp+=a==0x5A52B0?16:12;return;}
    case 0x593750:{unsigned self=c->ecx;M32(self+4)=arg(c,1);if(self==QR){Cpu q=*c;q.esp-=128;carbon_qrsplit_transition(&q,native_00854300);}c->esp+=12;return;}
    case 0x61BEF0:c->eax=0x440000;c->esp+=8;return;
    case 0x6136A0:c->eax=0;c->esp+=4;return;
    case 0x7BBED0:++starts;c->esp+=4;return;
    case 0x606B60:c->eax=arg(c,0)==0x9EC16C?1:2;c->esp+=4;return;
    case 0x11111111:case 0x11111112:++players;c->esp+=4;return;
    case 0x60CB50:c->eax=0x460000+players*0x100;M32(c->eax)=0x470000;M32(0x470034)=0x22222234;M32(0x470018)=0x22222218;M32(0x47002C)=0x2222222C;M32(0x470024)=0x22222224;c->esp+=8;return;
    case 0x22222234:ports[players-1]=arg(c,0);c->esp+=8;return;
    case 0x22222218:index_[players-1]=arg(c,0);c->esp+=8;return;
    case 0x2222222C:viewport[players-1]=arg(c,0);c->esp+=8;return;
    case 0x22222224:hud[players-1]=arg(c,0);c->esp+=8;return;
    case 0x7AA370:c->eax=0;c->esp+=4;return;
    case 0x5CA560:case 0x5A1B10:c->esp+=20;return;
    case 0x5EA670:c->eax=0;c->esp+=4;return;
    case 0x598540:c->esp+=16;return;
    default:break;
    }
    if(native_dispatch(c,a))return;
    fprintf(stderr,"unexpected dispatch %08X self=%08X\n",a,c->ecx);abort();
}
uint32_t call_guest(Cpu *c,uint32_t a,int n,const uint32_t *args){unsigned sp=c->esp;for(int i=n-1;i>=0;--i){c->esp-=4;M32(c->esp)=args[i];}c->esp-=4;M32(c->esp)=0xFEEDF00D;dispatch(c,a);c->esp=sp;return c->eax;}
int main(void){G=calloc(1,0xC00000);if(!G)return 2;proof();input_proof();memory_proof();printf("qrsplit checks=%u failures=%u\n",checks,failures);free(G);return failures?1:0;}
'''


def main():
    sys.path.insert(0, str(HERE))
    import private_padbind_test as pb
    import recomp
    base = HERE / 'out/carbon-base'
    if not (base / 'image.json').is_file():
        print('SKIP: Carbon translated output unavailable')
        return 3
    meta = json.loads((base / 'image.json').read_text())
    if not Path(meta['exe']).is_file():
        return 3
    pe = recomp.PE(meta['exe'], expected_sha256=meta['sha256'])
    # The retained native menu uses this localized Split Screen caption.
    assert pe.read(0x00853AD9,5).hex()=='68361dce37'
    starts = [int(v.removesuffix('u'), 16) for v in re.search(r'guest_func_addr\[\] = \{([^}]+)', (base/'table.c').read_text())[1].split(',')]
    bodies = {}
    for a in NATIVE:
        source = (base / f'NFSC_{starts.index(a)//800:02d}.c').read_text()
        name = f'carbon_orig_{a:08X}' if f'void carbon_orig_{a:08X}(' in source else f'f_{a:08X}'
        bodies[a] = pb.body(source, name).replace(name, f'native_{a:08X}', 1)
        assert hashlib.sha256(bodies[a].encode()).hexdigest()==BASELINES[a], hex(a)
    callees = {int(s,16) for body in bodies.values() for s in re.findall(r'f_([0-9A-F]{8})\(c\)', body)}
    native = '\n'.join(bodies.values())
    native += '\nstatic int native_dispatch(Cpu *c,uint32_t a){switch(a){\n'
    for a in NATIVE:
        native += f'case 0x{a:X}:' + ('++port_calls;' if a==0x572C90 else '') + f'native_{a:08X}(c);return 1;\n'
    native += 'default:return 0;}}\n'
    for a in sorted(callees):
        native += f'void f_{a:08X}(Cpu *c){{dispatch(c,0x{a:X});}}\n'
    ranges = ((0x854470, 0x39), (0x867E90, 0x70), (0x844D08, 0x1C), (0x9F8428, 0x11C), (0x9F96A4, 0x3C),
              (0xA5E038, 28*16), (0xA60C80, 0x120), (0x5FE2F4, 15), (0x9D0610, 0x90), (0x9C2888, 4),
              (0xA62C48, 8))
    native += 'static void init_image(void){\n'
    for a,n in ranges:
        native += '{static const unsigned char b[]={' + ','.join(map(str,pe.read(a,n))) + f'}};memcpy(G+0x{a:X},b,sizeof b);}}\n'
    native += '}\n'
    baseline = '\n'.join(f'void {name}(Cpu *c,void (*original)(Cpu *)){{original(c);}}' for name in HOOKS.values())
    implementation = (PRIVATE / 'carbon_qrsplit.c').read_text() if (PRIVATE / 'carbon_qrsplit.c').exists() else baseline
    if '--red' not in sys.argv:
        import private_hooks
        registry = private_hooks.load_registry(pe, [(a, starts[i+1] if i+1<len(starts) else a+16, 'fixture') for i,a in enumerate(starts)])
        owned = json.loads((PRIVATE/'hooks/qrsplit.json').read_text())['hooks']
        assert {int(row['address'],16):row['provider'] for row in owned} == HOOKS
        assert all(registry[a]['provider']==name for a,name in HOOKS.items())
        manifest = json.loads((PRIVATE/'features/qrsplit.json').read_text())
        assert manifest['bindings']['carbon_qrsplit.c']['sha256']==hashlib.sha256(implementation.encode()).hexdigest()
        ast = pb.command(['clang','-std=c11','-I',PRIVATE,'-I',ROOT/'runtime','-I',HERE,
                          '-fsyntax-only','-Xclang','-ast-dump=json',PRIVATE/'carbon_qrsplit.c'])
        sys.path.insert(0,str(PRIVATE))
        from quarantine import audit_tree
        accesses={(r['name'],kind,address) for r in audit_tree(json.loads(ast.stdout),[(0x400000,0xC00000)])
                  if r['name'].startswith('carbon_qrsplit_') for kind,address in r['accesses']}
        declared={(name,kind,address) for name,row in manifest['sources']['carbon_qrsplit.c']['guest_accesses'].items()
                  for kind,addresses in row.items() for address in addresses}
        assert accesses==declared, sorted(accesses^declared)
    with tempfile.TemporaryDirectory(prefix='private-qrsplit-') as td:
        tmp = Path(td)
        (tmp/'native.inc').write_text(native)
        padguest = (PRIVATE/'carbon_padguest.c').read_text()
        if 'void carbon_padguest_ports(' not in padguest:
            padguest += '\n#define carbon_padguest_ports(c, original) original(c)\n'
        (tmp/'carbon_padguest.c').write_text(padguest)
        (tmp/'fixture.c').write_text(HARNESS)
        def execute(label, code, expected, guest=padguest):
            if 'void carbon_qrsplit_memory(' not in code:
                code += '\n#define carbon_qrsplit_memory(c, original) original(c)\n'
            (tmp/'carbon_qrsplit.c').write_text(code)
            (tmp/'carbon_padguest.c').write_text(guest)
            binary = tmp / label
            pb.command(['clang','-std=c11','-O0','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',tmp,'-I',PRIVATE,'-I',ROOT/'runtime','-I',HERE,'-I',base,tmp/'fixture.c','-o',binary])
            result = pb.command([binary], expected)
            print(label + ': ' + result.stdout.strip())
        if '--red' in sys.argv:
            execute('original-menu', baseline, 1)
            return 0
        execute('good', implementation, 0)
        assert 'M32(c->esp + 4) = 2;' in padguest
        execute('one-fe-port', implementation, 1,
                padguest.replace('M32(c->esp + 4) = 2;', 'M32(c->esp + 4) = 1;', 1))
        execute('unscoped-fe-count', implementation, 1,
                padguest.replace('M32(c->esp) == 0x00572144u && ', '', 1))
        execute('one-split-kib', implementation.replace('M32(0x00A62C4Cu) = M32(0x00A62C48u);', '/* retain the native split placeholder */', 1), 1)
        execute('unscoped-split-budget', implementation.replace('pad_count() != 2 ||\n        ', '', 1), 1)
        execute('persistent-split-budget', implementation.replace('M32(0x00A62C4Cu) = saved;', '/* split field not restored */', 1), 1)
        execute('original-menu', baseline, 1)
        for label,old,new in (
            ('unscoped-option', 'M32(row + 0x74) != 0x13E4u || ', ''),
            ('wrong-label', '0x37CE1D36u', '0x2818EFEFu'),
            ('lost-cancellation', 'if (state == 2) carbon_qrsplit_single(c);', '/* cancelled split retained */'),
            ('wrong-return-state', 'uint32_t attach[] = {child, 8, 1};', 'uint32_t attach[] = {child, 0, 1};'),
            ('duplicate-owner', 'if (p0 != 0 || p1 != 1)', 'if (0 && (p0 != 0 || p1 != 1))'),
        ):
            assert old in implementation
            execute(label,implementation.replace(old,new,1),1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
