/* Two main views share a target, but own descriptors, cameras and projections.
 * 0071BCA0 runs before the camera loop; 007103C0 already culls both active
 * views. 0072EBA0 retains frame-wide preparation once.
 * Each view owns a complete native capture/world/post sequence and its backing
 * targets. A failed allocation retains the raw two-view world fallback. */
#include "carbon_splitworld.h"
#include <stdlib.h>
#include <math.h>

#define CS_P1 0x00B4AF90u
#define CS_P2 0x00B4B010u
static uint32_t storage, descriptors[2], native_descriptors[2], rectangles[2][4];
static uint8_t native_active[2];
static int installed, in_frame, cleared, effects_done, effects_allocated;
static uint32_t effect_view, effect_storage, guest_effect_p2;
static uint32_t effect_indices[2];
uint32_t carbon_splitworld_effect_view(void){return effect_view;}
int carbon_splitworld_dispatch_done(void){return in_frame && effects_done && !effect_view;}
static uint32_t probe_camera, native_camera;

/* A rendering-only probe for jobs preceding the two-player front end. It uses
 * a copy of the live camera, shifted eight metres sideways. It does
 * not create a second player or change simulation/input ownership. */
static int cs_probe(void) {
    static int enabled = -1;
    if (!diag_on) return 0;
    if (enabled < 0) {
        const char *e = getenv("BOOT_DIAG_SPLITWORLD");
        enabled = e && !strcmp(e, "1");
    }
    return enabled;
}

int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]) {
    if (!installed || (view != CS_P1 && view != CS_P2)) return 0;
    if (rect) memcpy(rect, rectangles[view == CS_P2], sizeof rectangles[0]);
    return 1;
}

/* Native initialization assigns both players to the primary target. Keep that
 * full-size descriptor intact: mirrors, frame clears and reset still use it. */
static void cs_layout(Cpu *c, void (*original)(Cpu *)) {
    if (native_camera && M32(CS_P2 + 0x40) == probe_camera) M32(CS_P2 + 0x40) = native_camera;
    native_camera = 0;
    if (installed) {
        for (unsigned i = 0; i < 2; ++i) {
            uint32_t view = CS_P1 + 0x80u * i;
            if (M32(view + 0x50) == descriptors[i]) {
                M32(view + 0x50) = native_descriptors[i];
                M8(view + 0xC) = native_active[i];
            }
        }
        installed = 0;
    }
    original(c);
    /* 007655D0 creates two local players only for simulation mode 1. */
    if (M32(0x00A99BBCu) != 6) return;
    int probe = cs_probe() && M32(0x00B4D854u) != 1;
    if (M32(0x00B4D854u) != 1 && !probe) return;
    if (!M32(CS_P1) || !M32(CS_P2) || !M32(CS_P1 + 0x40) || !M32(CS_P2 + 0x40)) return;
    uint32_t source = M32(CS_P1 + 0x50);
    /* The PC render selector can leave the main target inactive even after
     * mode 1 has created both local players. Their private descriptors own
     * activation; only the single-player probe requires a live native view. */
    if (!source || (probe && !M8(CS_P1 + 0xC))) return;
    uint32_t w = M32(source + 0x14), h = M32(source + 0x18);
    if (!w || h < 2) return;
    if (!storage) storage = galloc(0xA0);
    if (!storage) return;
    if (probe) {
        if (!probe_camera) probe_camera = galloc(0x100);
        if (!probe_camera) return;
        native_camera = M32(CS_P2 + 0x40);
        memcpy(G + probe_camera, G + M32(CS_P1 + 0x40), 0x100);
        MF32(probe_camera + 0x30) -= 8.0f;
        MF32(probe_camera + 0x40) -= 8.0f;
        M32(CS_P2 + 0x40) = probe_camera;
    }
    for (unsigned i = 0; i < 2; ++i) {
        uint32_t view = CS_P1 + 0x80u * i, d = storage + 0x20u * i;
        native_descriptors[i] = M32(view + 0x50);
        native_active[i] = M8(view + 0xC);
        descriptors[i] = d;
        memcpy(G + d, G + source, 0x1C);
        rectangles[i][0] = 0; rectangles[i][1] = i ? h / 2 : 0;
        rectangles[i][2] = w; rectangles[i][3] = i ? h - h / 2 : h / 2;
        /* 00727230 and shader setup index view/platform state by descriptor+4. */
        M32(d + 4) = M32(view + 8);
        M32(d + 0x10) = 1;
        M32(d + 0x14) = w; M32(d + 0x18) = rectangles[i][3];
        M32(view + 0x50) = d; M8(view + 0xC) = 1;
    }
    installed = 1;
}

void carbon_splitworld_layout(Cpu *c, void (*original)(Cpu *)) {
    cs_layout(c,original);
    if(!installed && effects_allocated){carbon_spliteffects_reset();effects_allocated=0;}
}

static void cs_device(Cpu *c, uint32_t method, int n, const uint32_t *args) {
    call_guest(c, M32(M32(args[0]) + method), n, args);
}
static void cs_bounds(Cpu *c, const uint32_t r[4], int clip) {
    uint32_t p = storage + 0x40, device = M32(0x00AB0ABCu);
    memcpy(G + p, r, 16); M32(p + 16) = 0; MF32(p + 20) = 1;
    uint32_t vp[2] = {device, p}; cs_device(c, 0xBC, 2, vp);
    M32(p + 24) = r[0]; M32(p + 28) = r[1];
    M32(p + 32) = r[0] + r[2]; M32(p + 36) = r[1] + r[3];
    uint32_t scissor[2] = {device, p + 24}; cs_device(c, 0x12C, 2, scissor);
    uint32_t state[3] = {device, 174, (uint32_t)clip}; cs_device(c, 0xE4, 3, state);
}

void carbon_splitworld_bind(Cpu *c, void (*original)(Cpu *)) {
    if(effect_view){original(c);return;}
    uint32_t sp = c->esp, d = M32(sp + 4);
    if (!installed || (d != descriptors[0] && d != descriptors[1])) { original(c); return; }
    uint32_t clear = M32(sp + 8);
    /* Native binding clears before setting its zero-origin viewport. Both
     * players share colour AND depth; clear them once before either draws. */
    M32(sp + 8) = 0; original(c); M32(sp + 8) = clear;
    Cpu work = *c;
    if (in_frame && !cleared) {
        uint32_t full[4] = {0, 0, rectangles[0][2], rectangles[0][3] + rectangles[1][3]};
        cs_bounds(&work, full, 0);
        uint32_t args[7] = {M32(0x00AB0ABCu), 0, 0, 7, M32(sp + 12), 0x3F800000u, 0};
        cs_device(&work, 0xAC, 7, args); cleared = 1;
    }
    cs_bounds(&work, rectangles[d == descriptors[1]], 1);
}

void carbon_splitworld_frame(Cpu *c, void (*original)(Cpu *)) {
    int previous = in_frame;
    in_frame = installed; cleared = 0; effects_done = 0;
    original(c);
    if (installed) M32(CS_P1 + 0x50) = descriptors[0];
    in_frame = previous;
}

/* 0072E7C0..0072E83D: native animated-world shader scope. */
static void cs_animated(Cpu *c, uint32_t view) {
    uint32_t sh = M32(0x00B42FECu), device = M32(0x00AB0ABCu);
    M32(0x00AB0BA4u) = sh;
    c->ecx = sh; call_guest(c, M32(M32(sh) + 0x10), 0, NULL);
    uint32_t declaration[2] = {device, M32(sh + 0x48)};
    cs_device(c, 0x15C, 2, declaration);
    uint32_t effect = M32(sh + 0x44), passes = storage + 0x80;
    uint32_t begin[3] = {effect, passes, 0};
    call_guest(c, M32(M32(effect) + 0xFC), 3, begin);
    M32(sh + 0x14) = M32(passes);
    uint32_t pass[2] = {effect, 0};
    call_guest(c, M32(M32(effect) + 0x100), 2, pass);
    call_guest(c, 0x007A2380u, 1, &view);
    call_guest(c, M32(M32(effect) + 0x108), 1, &effect);
    c->ecx = sh; call_guest(c, M32(M32(sh) + 0x14), 0, NULL);
    call_guest(c, M32(M32(effect) + 0x10C), 1, &effect);
    M32(0x00AB0BA4u) = 0;
}

/* 0072E5B6..0072E6FF: sky, scenery, vehicles and route geometry, in native
 * order. Context is the frame-wide 007103C0 result, not a second preparation.
 * The later 00726430/007268E0/007D8240 paths clear shared intermediate/main
 * targets and assume a player-owned effect list. They belong to view effects. */
static void cs_world(Cpu *c, uint32_t view, uint32_t context) {
    uint32_t fx = M32(view + 0x6C), strength = M32(fx + 0x290);
    c->ecx = M32(0x00B77F34u); call_guest(c, 0x007F12A0u, 1, &strength);
    uint32_t bind[3] = {M32(view + 0x50), 1, 0};
    call_guest(c, 0x0070DD30u, 3, bind);
    call_guest(c, 0x0071BED0u, 0, NULL);
    cs_bounds(c, rectangles[view == CS_P2], 1);
    uint32_t sky[3] = {view, 1, M32(0x00A63D20u)};
    call_guest(c, 0x0072E070u, 3, sky);
    MF32(0x00A650E0u) = 1;
    call_guest(c, 0x0072C9B0u, 0, NULL);
    uint32_t scenery[3] = {view, M32(0x00AB0A98u) | 0x20u, c->ebp};
    c->ecx = context; call_guest(c, 0x0079AFA0u, 3, scenery);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    c->ecx = context;
    uint32_t model[2] = {view, call_guest(c, 0x0079AF60u, 1, &view)};
    call_guest(c, 0x007D1C40u, 2, model);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    call_guest(c, 0x0042ADF0u, 1, &view);
    call_guest(c, 0x0072C9B0u, 0, NULL);
    cs_animated(c, view);
    /* 0072E84E: live vehicles, including the native extra-renderable list. */
    uint32_t vehicles[2] = {view, 0};
    call_guest(c, 0x007CCA20u, 2, vehicles);
    call_guest(c, 0x0072C9B0u, 0, NULL);
}


/* Capture cameras are native: 007D5C60 -> 007218A0 constructs the six cube
 * views from the primary camera/car. Scope that primary to the owner, then
 * cull only those captures into a separate context. Main world preparation
 * remains the frame's single 007103C0 invocation. */
static void cs_captures(Cpu *c, uint32_t view) {
    uint32_t quality=M32(0x00A65340u),road=0x00B4B110u;
    uint32_t camera=M32(road+0x40),fx=M32(road+0x6C),rd=M32(road+0x50);
    uint8_t road_active=M8(road+0xC);
    uint32_t road_enabled=rd?M32(rd+0x10):0,cube_fx[6];
    M32(road+0x40)=M32(view+0x40);M32(road+0x6C)=M32(view+0x6C);
    if(rd && M32(0x00A65358u) && M32(rd+8)){M8(road+0xC)=1;M32(rd+0x10)=1;}
    for(unsigned i=0;i<6;i++) {
        uint32_t capture=0x00B4BA10u+0x80u*i;
        cube_fx[i]=M32(capture+0x6C);M32(capture+0x6C)=M32(view+0x6C);
    }
    if(quality) {
        /* A fresh owner must have all faces before its first sample. The
         * decoded highest-quality schedule refreshes all six (A63B18/28). */
        M32(0x00A65340u)=3;
        float car[3];
        if(!carbon_splitworld_position(view,car))
            for(unsigned j=0;j<3;j++)car[j]=MF32(M32(view+0x40)+0x40+4*j);
        {
            uint32_t current_camera=M32(view+0x40),primary_camera=M32(CS_P1+0x40);
            for(unsigned j=0;j<3;j++) {
                MF32(effect_storage+0x40+4*j)=MF32(current_camera+0x40+4*j)+MF32(0x00B74E50u+4*j);
                MF32(effect_storage+0x50+4*j)=car[j]+MF32(0x00A7A590u+4*j);
            }
            uint32_t args[2]={effect_storage+0x40,effect_storage+0x50};
            M32(CS_P1+0x40)=current_camera;
            c->ecx=0x00AB0F80u;call_guest(c,0x007218A0u,2,args);
            M32(CS_P1+0x40)=primary_camera;
        }
    }
    uint32_t context=effect_storage+0x100;
    memset(G+context,0,0x3D0);
    for(unsigned i=0;i<7;i++) {
        uint32_t capture=i?0x00B4BA10u+0x80u*(i-1):road;
        uint32_t d=M32(capture+0x50);
        if(!M8(capture+0xC) || !d || !M32(d+0x10))continue;
        uint32_t setup[5]={capture,0,0,0,1};
        c->ecx=M32(capture);call_guest(c,0x0071B780u,5,setup);
        uint32_t cull[2]={capture,i?0x2000u:0};
        c->ecx=context;call_guest(c,0x0079FF30u,2,cull);
    }
    c->ecx=context;call_guest(c,0x007A4BA0u,0,NULL);
    if(M32(0x00A65358u))call_guest(c,0x0072E0F0u,1,&context);
    if(quality)for(unsigned i=0;i<6;i++) {
        uint32_t args[2]={0x00B4BA10u+0x80u*i,context};
        call_guest(c,0x0072E460u,2,args);
    }
    M32(0x00A65340u)=quality;
    M32(road+0x40)=camera;M32(road+0x6C)=fx;M8(road+0xC)=road_active;
    if(rd)M32(rd+0x10)=road_enabled;
    for(unsigned i=0;i<6;i++)M32(0x00B4BA10u+0x80u*i+0x6Cu)=cube_fx[i];
}

static int cs_effect_worlds(Cpu *c,void (*original)(Cpu *),uint32_t context) {
    if(!carbon_spliteffects_begin(CS_P1))return 0;
    effects_allocated=1;
    if(!effect_storage)effect_storage=galloc(0x500);
    if(!effect_storage){carbon_spliteffects_end(CS_P1);return 0;}
    Cpu work=*c;
    if(!guest_effect_p2) {
        uint32_t size=0xD0;
        guest_effect_p2=call_guest(&work,0x006A1560u,1,&size);
        if(!guest_effect_p2){carbon_spliteffects_end(CS_P1);return 0;}
        work.ecx=guest_effect_p2;call_guest(&work,0x00713330u,0,NULL);
    }
    uint32_t descriptor1=M32(CS_P1+0x50);
    uint32_t native_fx=M32(0x00AB0B80u),native_index=M32(0x00AB0B4Cu);
    uint32_t descriptor2=M32(CS_P2+0x50),argument=M32(c->esp+4);
    for(unsigned i=0;i<2;i++) {
        uint32_t view=CS_P1+0x80u*i;
        if(i && !carbon_spliteffects_begin(view)) {
            M32(0x00AB0B80u)=native_fx;M32(0x00AB0B4Cu)=native_index;
            M32(CS_P1+0x50)=descriptor1;M32(CS_P2+0x50)=descriptor2;
            M32(c->esp+4)=argument;effect_view=0;return 0;
        }
        effect_view=view;
        memcpy(G+effect_storage,G+native_descriptors[0],0x1C);
        M32(effect_storage+4)=M32(view+8);
        M32(effect_storage+0x10)=1;
        M32(view+0x50)=effect_storage;
        M32(0x00AB0B80u)=i?guest_effect_p2:native_fx;
        M32(0x00AB0B4Cu)=i?effect_indices[1]:native_index;
        work=*c;
        cs_captures(&work,view);
        /* 00726430 and 00729970 restore literal scene/car-blur descriptors.
         * 00727230 then obtains the car's shader camera from descriptor+4,
         * independently of the view used for its successful frustum test. */
        uint32_t final_owner=M32(0x00AB04D4u),world_owner=M32(0x00AB04F0u),blur_owner=M32(0x00AB0598u);
        M32(0x00AB04D4u)=M32(0x00AB04F0u)=M32(0x00AB0598u)=M32(view+8);
        work=*c;M32(work.esp+4)=view;
        original(&work);
        work.esp=c->esp; /* Guest helpers use scratch below the live caller frame. */
        call_guest(&work,0x0072C9B0u,0,NULL);
        call_guest(&work,0x0073EA60u,1,&context);
        call_guest(&work,0x00729770u,1,&view);
        call_guest(&work,0x0072C9B0u,0,NULL);
        M32(0x00AB04D4u)=final_owner;M32(0x00AB04F0u)=world_owner;M32(0x00AB0598u)=blur_owner;
        effect_indices[i]=M32(0x00AB0B4Cu);
        carbon_spliteffects_end(view);
        if(diag_on) {
            static unsigned reports;
            if(reports++<4)diag_event("carbon spliteffects camera: view=%08X camera=%08X platform=%08X projection=%.9g,%.9g post=%08X cube_faces=6",view,M32(view+0x40),M32(view),MF32(M32(view)+0x40),MF32(M32(view)+0x54),M32(0x00AB0B80u));
        }
        M32(CS_P1+0x50)=descriptor1;
        M32(CS_P2+0x50)=descriptor2;
        M32(c->esp+4)=argument;
        effect_view=0;
    }
    M32(0x00AB0B80u)=native_fx;M32(0x00AB0B4Cu)=effect_indices[0];
    effects_done=1;
    /* Native caller continues with its shared context cleanup, then skips the
     * already completed post dispatch. Restore the main atlas binding for FE. */
    M32(CS_P1+0x50)=native_descriptors[0];
    uint32_t bind[3]={0x00AB04D0u,0,0};
    call_guest(&work,0x0070DD30u,3,bind);
    uint32_t full[4]={0,0,rectangles[0][2],rectangles[0][3]+rectangles[1][3]};
    cs_bounds(&work,full,0);
    return 1;
}

void carbon_splitworld_submit(Cpu *c, void (*original)(Cpu *)) {
    if (!in_frame || !installed || M32(c->esp + 4) != CS_P1) { original(c); return; }
    uint32_t context = M32(c->esp + 8);
    if(cs_effect_worlds(c,original,context)){c->esp+=4;return;}
    Cpu work = *c;
    cs_world(&work, CS_P1, context);
    cs_world(&work, CS_P2, context);
    /* Retain the native shared final update once. The existing post hook still
     * composes one full atlas; no player-local effect body is repeated here. */
    uint32_t view = CS_P1;
    work.ecx = M32(0x00AB0B80u); call_guest(&work, 0x007D2470u, 1, &view);
    M32(CS_P1 + 0x50) = native_descriptors[0];
    uint32_t bind[3] = {native_descriptors[0], 0, 0};
    call_guest(&work, 0x0070DD30u, 3, bind);
    uint32_t full[4] = {0, 0, rectangles[0][2], rectangles[0][3] + rectangles[1][3]};
    cs_bounds(&work, full, 0);
    c->esp += 4; /* 0072E5B0 is cdecl; the caller retains both arguments. */
    if (diag_on) {
        static unsigned reports;
        if (reports++ < 4)
            diag_event("carbon splitworld: views=%08x,%08x cameras=%08x,%08x rectangles=0,0,%u,%u/0,%u,%u,%u submissions=2 clears=1 probe=%d",
                       CS_P1, CS_P2, M32(CS_P1 + 0x40), M32(CS_P2 + 0x40),
                       rectangles[0][2], rectangles[0][3], rectangles[1][1], rectangles[1][2], rectangles[1][3], native_camera != 0);
    }
}

/* 0076FC87..A5 appends normal interfaces to A9FF5C/A9FF64; their view ID
 * getter 0076E6F0 (vtable+30) returns interface+14. Position is
 * read through the same validated Simable/RigidBody chain as single player. */
int carbon_splitworld_position(uint32_t view, float position[3]) {
    if(!installed || (view!=CS_P1 && view!=CS_P2))return 0;
    uint32_t owner=native_camera?M32(CS_P1+8):M32(view+8);
    uint32_t list=M32(0x00A9FF5Cu),count=M32(0x00A9FF64u),player=0;
    if(!list || !count || count>2)return 0;
    for(unsigned i=0;i<count;i++) {
        uint32_t p=M32(list+4*i),vt=p?M32(p):0;
        if(p>=8 && vt && M32(vt+4)==0x0076E810u &&
           M32(vt+0x30)==0x0076E6F0u && M32(p+0x14)==owner){player=p;break;}
    }
    if(!player)return 0;
    uint32_t sim=M32(player-8),sv=sim?M32(sim):0;
    if(!sv || M32(sv+0x60)!=0x006D7EA0u)return 0;
    uint32_t body=M32(sim+0x4C),bv=body?M32(body):0;
    if(!bv || M32(bv+0x20)!=0x006C6FF0u)return 0;
    uint32_t holder=M32(body+0x30),state=holder?M32(holder):0;
    if(!state)return 0;
    float p[3];memcpy(p,G+state+0x10,sizeof p);
    for(unsigned j=0;j<3;j++)if(!isfinite(p[j]))return 0;
    position[0]=p[2];position[1]=-p[0];position[2]=p[1];return 1;
}

void carbon_splitworld_update(Cpu *c,void (*original)(Cpu *)) {
    if(!effect_view){original(c);return;}
    uint32_t sp=c->esp,view=M32(sp+4);
    if(effect_view && view==CS_P1)M32(sp+4)=effect_view;
    /* 007133C0 takes a view ID; 00726430 passes literal player one. */
    if(view==1)M32(sp+4)=M32(effect_view+8);
    original(c);
    M32(sp+4)=view;
}

void carbon_splitworld_auxiliary(Cpu *c,void (*original)(Cpu *)) {
    if(carbon_splitworld_dispatch_done()){c->esp+=4;return;}
    original(c);
}

/* 007D77B0 obtains the view at FX+288, then dereferences the first +44
 * renderable even when the native sentinel check produced NULL (007D7852).
 * A carless view has no vehicle weather update. The shifted-camera diagnostic
 * views the same physical car, so it may borrow that first node for this read
 * only; its camera, FX state and list sentinel remain its own. */
static int cs_weather_mover(uint32_t head,uint32_t sentinel) {
    if(head<4 || head==sentinel)return 0;
    uint32_t vt=M32(head-4);
    return vt && M32(vt+0x10);
}
void carbon_splitworld_weather(Cpu *c,void (*original)(Cpu *)) {
    if(!effect_view){original(c);return;}
    uint32_t view=M32(c->ecx+0x288);
    if(view!=effect_view){original(c);return;}
    uint32_t sentinel=view+0x44,head=M32(sentinel);
    int borrowed=0;
    if(!cs_weather_mover(head,sentinel) && native_camera && view==CS_P2) {
        uint32_t candidate=M32(CS_P1+0x44);
        if(cs_weather_mover(candidate,CS_P1+0x44)) {
            M32(sentinel)=candidate;borrowed=1;
        }
    }
    if(!cs_weather_mover(M32(sentinel),sentinel)){c->esp+=4;return;}
    original(c);
    if(borrowed)M32(sentinel)=head;
}
