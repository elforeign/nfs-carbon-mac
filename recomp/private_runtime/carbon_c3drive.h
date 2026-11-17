/* Test-only route follower. Its path is the loaded native road graph: nodes
 * B77EC8 (stride 32: +0 XYZ, +16 degree, +18 u16 segment slots) and segments
 * B77ECC (stride 22: +0/+2 endpoints, +12/+14 handle lengths x500/65535,
 * +16/+19 signed-byte control directions at the end/start node). */
#define CARBON_C3DRIVE_PATH 1024
#define CARBON_C3DRIVE_DEAD .18
static float carbon_c3drive_lx, carbon_c3drive_rt, carbon_c3drive_lt;
static int carbon_c3drive_active, carbon_c3drive_done, carbon_c3drive_built;
static int carbon_c3drive_airborne, carbon_c3drive_landed, carbon_c3drive_logged, carbon_c3drive_straight;
static uint32_t carbon_c3drive_tick;
static double carbon_c3drive_lip_time = -1.;
static uint64_t carbon_c3drive_arrived, carbon_c3drive_second;
static float carbon_c3drive_path[CARBON_C3DRIVE_PATH][3], carbon_c3drive_arc[CARBON_C3DRIVE_PATH];
static float carbon_c3drive_vmax[CARBON_C3DRIVE_PATH];
static unsigned carbon_c3drive_count, carbon_c3drive_index;
/* Route progress, recovery and end, all in simulation seconds. */
static double carbon_c3drive_best, carbon_c3drive_progress_time, carbon_c3drive_recover_time;
static double carbon_c3drive_reverse_until = -1.;
static const char *carbon_c3drive_reason;

static int carbon_c3drive_direction(void) {
    const char *route = getenv("NFS_CARBON_C3_ROUTE");
    if (!route || !*route) return 0;
    const char *ai = getenv("BOOT_AUTODRIVE"), *pad = getenv("BOOT_PAD");
    const char *skip = getenv("NFS_CARBON_SKIPFE"), *start = getenv("NFS_CARBON_SKIPFE_START");
    if (!ai || strcmp(ai,"1") || !pad || strcmp(pad,"sim") ||
        !skip || strcmp(skip,"1") || !start || !*start) return 0;
    return !strcmp(route,"forward") ? 1 : !strcmp(route,"reverse") ? -1 : 0;
}

/* NFS_CARBON_C3_ROUTE=log on a crossing start: the same c3tick trace of a car
 * someone else drives. Never a control, never the native AI handover. */
static int carbon_c3drive_logging(void) {
    const char *route = getenv("NFS_CARBON_C3_ROUTE");
    const char *skip = getenv("NFS_CARBON_SKIPFE"), *start = getenv("NFS_CARBON_SKIPFE_START");
    return route && !strcmp(route,"log") && skip && !strcmp(skip,"1") && start && *start;
}

/* Positive stick is right in physics XZ: +X when heading +Z. */
static float carbon_c3drive_steer(double dx, double dz, double hx, double hz) {
    double right = hz*dx-hx*dz;
    double length2 = dx*dx+dz*dz;
    double value = atan2(5.4*right, fmax(length2,1.))/.5;
    return (float)fmax(-1.,fmin(1.,value));
}

/* Called only by the simulated-pad pressure hook, before native filtering.
 * A completed driver asks the Cocoa caller to use its existing clean quit. */
int carbon_c3drive_pad(int idx, float *lx, float *rt, float *lt) {
    if (idx || !carbon_c3drive_direction() || !carbon_c3drive_active) return 0;
    *lx = carbon_c3drive_lx; *rt = carbon_c3drive_rt; *lt = carbon_c3drive_lt;
    return carbon_c3drive_done ? 2 : 1;
}

static unsigned carbon_c3drive_node(unsigned i, int direction) {
    if (direction < 0) i = 51-i;
    return i < 16 ? 8739+i : i < 51 ? 8988+i-16 : 1534;
}

/* Dense centre line (4 m steps) along each native segment's cubic, and a speed
 * limit from its curvature: 8 m/s2 sideways, 5 m/s2 braking for what is ahead. */
static void carbon_c3drive_build(uint32_t nodes, uint32_t segments, int direction) {
    unsigned n = 0;
    for (unsigned i=0;i<51;++i) {
        unsigned a=carbon_c3drive_node(i,direction), b=carbon_c3drive_node(i+1,direction);
        double pa[3],pb[3],c1[3],c2[3];
        for (unsigned k=0;k<3;++k) {
            pa[k]=MF32(nodes+32*a+4*k);pb[k]=MF32(nodes+32*b+4*k);
            c1[k]=pa[k]+(pb[k]-pa[k])/3;c2[k]=pb[k]+(pa[k]-pb[k])/3;
        }
        for (unsigned j=0;segments && j<M8(nodes+32*a+16) && j<7;++j) {
            uint32_t s=segments+22*M16(nodes+32*a+18+2*j);
            unsigned s0=M16(s),s1=M16(s+2);
            if (!((s0==a && s1==b) || (s0==b && s1==a))) continue;
            double start=M16(s+14)*500./65535, end=M16(s+12)*500./65535;
            for (unsigned k=0;k<3;++k) {
                double head=MF32(nodes+32*s0+4*k)+(int8_t)M8(s+19+k)/127.*start;
                double tail=MF32(nodes+32*s1+4*k)+(int8_t)M8(s+16+k)/127.*end;
                c1[k]=s0==a ? head : tail;c2[k]=s0==a ? tail : head;
            }
            break;
        }
        unsigned steps=(unsigned)fmax(2.,ceil(hypot(pb[0]-pa[0],pb[2]-pa[2])/4.));
        for (unsigned j=i?1:0;j<=steps && n<CARBON_C3DRIVE_PATH;++j,++n) {
            double t=(double)j/steps,u=1-t;
            for (unsigned k=0;k<3;++k)
                carbon_c3drive_path[n][k]=(float)(u*u*u*pa[k]+3*u*u*t*c1[k]+3*u*t*t*c2[k]+t*t*t*pb[k]);
            /* 25 m/s on every road: both ways the car held the path within
             * 2.1 m at that speed and wove up to 9.8 m off it at 36 m/s. */
            carbon_c3drive_vmax[n]=25.f;
        }
    }
    carbon_c3drive_arc[0]=0;
    for (unsigned i=1;i<n;++i)
        carbon_c3drive_arc[i]=carbon_c3drive_arc[i-1]+(float)hypot(
            carbon_c3drive_path[i][0]-carbon_c3drive_path[i-1][0],
            carbon_c3drive_path[i][2]-carbon_c3drive_path[i-1][2]);
    for (unsigned i=3;i+3<n;++i) {
        const float *p=carbon_c3drive_path[i-3],*q=carbon_c3drive_path[i],*r=carbon_c3drive_path[i+3];
        double turn=remainder(atan2(r[0]-q[0],r[2]-q[2])-atan2(q[0]-p[0],q[2]-p[2]),2*M_PI);
        double curvature=fabs(turn)/fmax(1.,(carbon_c3drive_arc[i+3]-carbon_c3drive_arc[i-3])/2);
        if (curvature>1e-6) carbon_c3drive_vmax[i]=(float)fmin(carbon_c3drive_vmax[i],sqrt(8./curvature));
    }
    for (unsigned i=n-1;i-->0;)
        carbon_c3drive_vmax[i]=(float)fmin(carbon_c3drive_vmax[i],sqrt(
            (double)carbon_c3drive_vmax[i+1]*carbon_c3drive_vmax[i+1]+
            10.*(carbon_c3drive_arc[i+1]-carbon_c3drive_arc[i])));
    carbon_c3drive_count=n;carbon_c3drive_index=~0u;carbon_c3drive_built=direction;
    carbon_c3drive_best=0;carbon_c3drive_progress_time=carbon_c3drive_recover_time=-1.;
    carbon_c3drive_reverse_until=-1.;
}

/* Log-only trace: every tick within 60 m of either lip, else every 30 ticks.
 * Course direction comes from the velocity along the lip axis. */
static void carbon_c3drive_trace(const float *position, const float *velocity, float line[52][3]) {
    double along=(position[0]+2635.271)*.5383-(position[2]-7214.961)*.8428;
    double lateral=(position[0]+2635.271)*.8428+(position[2]-7214.961)*.5383;
    double course=.5383*velocity[0]-.8428*velocity[2];
    int direction=course<0 ? -1 : 1;
    uint32_t tick=M32(0x00B4CFD4u);
    if (!diag_on || ((along<-60. || along>94.05) && tick%30)) return;
    if (carbon_c3drive_logged && tick==carbon_c3drive_tick) return;
    carbon_c3drive_logged=1;carbon_c3drive_tick=tick;
    double nearest=1e30;
    for (unsigned i=0;i<51;++i) {
        double dx=line[i+1][0]-line[i][0],dz=line[i+1][2]-line[i][2],length2=dx*dx+dz*dz;
        double t=length2<.001 ? 0 : fmax(0.,fmin(1.,((position[0]-line[i][0])*dx+
                                                    (position[2]-line[i][2])*dz)/length2));
        nearest=fmin(nearest,hypot(position[0]-line[i][0]-t*dx,position[2]-line[i][2]-t*dz));
    }
    double error=atan2(direction*(.5383*velocity[2]+.8428*velocity[0]),direction*course)*57.29577951308232;
    diag_event("c3tick: tick=%u time=%.6f position=%.6f,%.6f,%.6f velocity=%.6f,%.6f,%.6f s=%.6f lateral=%.6f heading=%.6f wheels=%d graph_lateral=%.6f log_only=1",
               tick,MF32(0x00B4CFD8u),position[0],position[1],position[2],velocity[0],velocity[1],velocity[2],
               along,lateral,error,carbon_census_wheels(),nearest);
}

static int carbon_c3drive_frame(uint32_t sim, uint64_t now) {
    int direction = carbon_c3drive_direction(), logging = !direction && carbon_c3drive_logging();
    if (!direction && !logging) return 0;
    carbon_c3drive_active = 0;
    uint32_t nodes = M32(0x00B77EC8u), segments = M32(0x00B77ECCu);
    uint32_t vt = M32(sim), body = M32(sim+0x4C), bv = body ? M32(body) : 0;
    if (!nodes || !vt || M32(vt+0x60) != 0x006D7EA0u ||
        !bv || M32(bv+0x20) != 0x006C6FF0u) return 1;
    uint32_t holder = M32(body+0x30), state = holder ? M32(holder) : 0;
    if (!state) return 1;
    float position[3],velocity[3],forward[3],line[52][3];
    memcpy(position,gptr(state+0x10),sizeof position);
    memcpy(velocity,gptr(state+0x20),sizeof velocity);
    /* Body matrix row 2 (forward), as 006C70E0 returns it. */
    memcpy(forward,gptr(state+0x90),sizeof forward);
    for (unsigned k=0;k<3;++k)
        if (!isfinite(position[k]) || !isfinite(velocity[k])) return 1;
    for (unsigned i=0;i<52;++i) {
        uint32_t node = nodes+32*carbon_c3drive_node(i,logging ? 1 : direction);
        memcpy(line[i],gptr(node),sizeof line[i]);
        for (unsigned k=0;k<3;++k) if (!isfinite(line[i][k])) return 1;
    }
    if (logging) {
        carbon_c3drive_trace(position,velocity,line);
        return 1;
    }
    if (carbon_c3drive_built != direction) carbon_c3drive_build(nodes,segments,direction);
    double speed = sqrt((double)velocity[0]*velocity[0]+(double)velocity[1]*velocity[1]+
                        (double)velocity[2]*velocity[2]);
    /* The checker's own measure: distance to the node polyline. */
    double nearest = 1e30, fraction = 0;
    unsigned segment = 0;
    for (unsigned i=0;i<51;++i) {
        double dx=line[i+1][0]-line[i][0],dz=line[i+1][2]-line[i][2];
        double length2=dx*dx+dz*dz;
        if (length2 < .001) continue;
        double t=fmax(0.,fmin(1.,((position[0]-line[i][0])*dx+
                                  (position[2]-line[i][2])*dz)/length2));
        double distance=hypot(position[0]-line[i][0]-t*dx,position[2]-line[i][2]-t*dz);
        if (distance < nearest) {nearest=distance;segment=i;fraction=t;}
    }
    (void)fraction;
    /* Nearest dense point, searched near the last one once known (whole path
     * when nothing there is within 30 m). */
    unsigned count=carbon_c3drive_count, first=0, last=count-1, here=0;
    if (carbon_c3drive_index < count) {
        first=carbon_c3drive_index>25 ? carbon_c3drive_index-25 : 0;
        last=carbon_c3drive_index+75<count ? carbon_c3drive_index+75 : count-1;
    }
    double closest=1e30;
    for (int pass=0;pass<2 && closest>30.;++pass,first=0,last=count-1)
        for (unsigned i=first;i<=last;++i) {
            double d=hypot(position[0]-carbon_c3drive_path[i][0],position[2]-carbon_c3drive_path[i][2]);
            if (d<closest) {closest=d;here=i;}
        }
    carbon_c3drive_index=here;
    double ahead=fmax(8.,fmin(24.,speed*.6));
    unsigned aim=here;
    while (aim+1<count && carbon_c3drive_arc[aim]-carbon_c3drive_arc[here]<ahead) ++aim;
    double tx=carbon_c3drive_path[aim][0],tz=carbon_c3drive_path[aim][2];
    /* Velocity course at speed (as part 5 measured the bridge); below 8 m/s the
     * body's facing, because a slow or blocked car's velocity is not where it points. */
    double hx=velocity[0],hz=velocity[2],planar=hypot(hx,hz);
    if (planar<8. && isfinite(forward[0]) && isfinite(forward[2]) && hypot(forward[0],forward[2])>.1) {
        hx=forward[0];hz=forward[2];planar=hypot(hx,hz);
    }
    if (planar<.001) {
        unsigned next=here+1<count ? here+1 : here, prev=next ? next-1 : 0;
        hx=carbon_c3drive_path[next][0]-carbon_c3drive_path[prev][0];
        hz=carbon_c3drive_path[next][2]-carbon_c3drive_path[prev][2];
        planar=hypot(hx,hz);
    }
    if (planar<.001) return 1;
    /* Fixed decoded lip axis, shared by both directions. */
    double along=(position[0]+2635.271)*.5383-(position[2]-7214.961)*.8428;
    double lateral=(position[0]+2635.271)*.8428+(position[2]-7214.961)*.5383;
    double progress=direction>0 ? along : 34.05-along;
    double crossing=direction>0 ? 34.05 : 33.85;
    int wheels=carbon_census_wheels();
    if (progress>=-130. && progress<=0.) carbon_c3drive_straight=1;
    if (carbon_c3drive_straight && wheels==0) carbon_c3drive_airborne=1;
    if (progress>=crossing && wheels>0 && carbon_c3drive_airborne) carbon_c3drive_landed=1;
    int lip_aim=carbon_c3drive_straight && !carbon_c3drive_landed;
    /* From 130 m before the take-off lip until the landing the car follows the
     * line through both decks' centres instead of the road graph, by the same
     * law with a look-ahead of at least 30 m: the graph meets that line 3.5
     * degrees off at the ramp, where the sprinting car cannot take a kink. */
    if (lip_aim) {
        double ux=18.87/34.19,uz=-28.51/34.19;
        double t=(position[0]+2636.45)*ux+(position[2]-7214.21)*uz+direction*fmax(ahead,30.);
        tx=-2636.45+t*ux;tz=7214.21+t*uz;
    }
    carbon_c3drive_lx=carbon_c3drive_steer(tx-position[0],tz-position[2],hx/planar,hz/planar);
    /* The game ignores a stick under about 0.18 and turns at the pursuit law's
     * own rate beyond it (0.175 /m per unit at 20-28 m/s), so the stick starts
     * at that edge. The rate falls with speed squared above 25 m/s (0.07 at
     * 37 m/s). The term beyond the edge is held to 13 m/s2 sideways: sticks
     * of 0.34-0.52, 17-26 m/s2, are where the car slid and wove. */
    if (carbon_c3drive_lx!=0) {
        double most=13./(.175*fmin(fmax(speed*speed,1.),625.));
        carbon_c3drive_lx=(float)copysign(fmin(1.,CARBON_C3DRIVE_DEAD+fmin(fabs(carbon_c3drive_lx),most)),
                                          carbon_c3drive_lx);
    }
    unsigned native=carbon_c3drive_node(segment,direction);
    double target=carbon_c3drive_vmax[here];
    /* Full throttle for the last 130 m; on the far side the road speed again. */
    int bridge=progress>=-130. && !carbon_c3drive_landed;
    if (bridge) target=45.;
    carbon_c3drive_rt=(float)fmax(0.,fmin(1.,.25+.18*(target-speed)));
    carbon_c3drive_lt=(float)fmax(0.,fmin(1.,.12*(speed-target-1.)));
    if (bridge) {carbon_c3drive_rt=1;carbon_c3drive_lt=0;}
    /* 0076ADA0 advances cumulative B4CFD4 and elapsed B4CFD8 each tick.
     * B4CFDC resets every dispatch; Present can repeat within one tick. */
    double sim_time=MF32(0x00B4CFD8u);
    uint32_t tick=M32(0x00B4CFD4u);
    if (progress>=0. && carbon_c3drive_lip_time<0.) carbon_c3drive_lip_time=sim_time;
    double end_distance=hypot(position[0]-line[51][0],position[2]-line[51][2]);
    if (end_distance<=40. && segment>=49) {
        if (!carbon_c3drive_arrived) carbon_c3drive_arrived=now;
        carbon_c3drive_rt=0;carbon_c3drive_lt=1;
    }
    /* Progress is the furthest point reached along the path. A car under 4 m/s
     * with none for 3 s reverses for 2 s with mirrored steer, then tries again;
     * none for 10 s ends the run. */
    if (carbon_c3drive_progress_time<0. || sim_time<carbon_c3drive_progress_time)
        carbon_c3drive_progress_time=carbon_c3drive_recover_time=sim_time;
    if (carbon_c3drive_arc[here]>carbon_c3drive_best+2.) {
        carbon_c3drive_best=carbon_c3drive_arc[here];
        carbon_c3drive_progress_time=carbon_c3drive_recover_time=sim_time;
    }
    if (!carbon_c3drive_arrived && !lip_aim) {
        if (carbon_c3drive_reverse_until<0. && speed<4. && sim_time-carbon_c3drive_recover_time>=3.) {
            carbon_c3drive_reverse_until=sim_time+2.;
            if (diag_on) diag_event("c3drive: recovery reverse at %.3f,%.3f,%.3f arc=%.1f",
                                    position[0],position[1],position[2],carbon_c3drive_best);
        }
        if (carbon_c3drive_reverse_until>=0.) {
            if (sim_time<carbon_c3drive_reverse_until) {
                carbon_c3drive_rt=0;carbon_c3drive_lt=1;carbon_c3drive_lx=-carbon_c3drive_lx;
            } else {
                carbon_c3drive_reverse_until=-1.;carbon_c3drive_recover_time=sim_time;
            }
        }
    }
    if (!carbon_c3drive_arrived && sim_time-carbon_c3drive_progress_time>=10.) carbon_c3drive_reason="no-progress";
    if (carbon_c3drive_arrived && now-carbon_c3drive_arrived>=5000000000ull) carbon_c3drive_reason="arrived";
    if (carbon_c3drive_reason && !carbon_c3drive_done) {
        carbon_c3drive_done=1;
        if (diag_on) diag_event("c3drive: end reason=%s position=%.3f,%.3f,%.3f arc=%.1f of %.1f",
                                carbon_c3drive_reason,position[0],position[1],position[2],
                                carbon_c3drive_best,carbon_c3drive_arc[count-1]);
    }
    int bridge_trace=progress>=-60. &&
        (carbon_c3drive_lip_time<0. || sim_time-carbon_c3drive_lip_time<=10.);
    if (diag_on && (bridge_trace || tick%30==0) &&
        (!carbon_c3drive_logged || tick!=carbon_c3drive_tick)) {
        carbon_c3drive_logged=1;carbon_c3drive_tick=tick;
        /* Heading is the measured velocity course. */
        double error=atan2(direction*(.5383*velocity[2]+.8428*velocity[0]),
                           direction*(.5383*velocity[0]-.8428*velocity[2]))*57.29577951308232;
        diag_event("c3tick: tick=%u time=%.6f position=%.6f,%.6f,%.6f velocity=%.6f,%.6f,%.6f s=%.6f lateral=%.6f heading=%.6f wheels=%d point=%u graph_lateral=%.6f aim=%.6f,%.6f target=%.6f lx=%.6f rt=%.6f lt=%.6f lip_aim=%d forward=%.4f,%.4f index=%u path_lateral=%.3f",
                   tick,sim_time,position[0],position[1],position[2],velocity[0],velocity[1],velocity[2],
                   along,lateral,error,wheels,segment,nearest,tx,tz,target,
                   carbon_c3drive_lx,carbon_c3drive_rt,carbon_c3drive_lt,lip_aim,
                   forward[0],forward[2],here,closest);
    }
    carbon_c3drive_active=1;
    if (diag_on && (!carbon_c3drive_second || now-carbon_c3drive_second>=1000000000ull)) {
        carbon_c3drive_second=now;
        diag_event("c3drive: point=%u node=%u lateral=%.3f speed=%.3f target=%.3f lx=%.4f rt=%.3f lt=%.3f arrived=%d done=%d",
                   segment,native,nearest,speed,target,carbon_c3drive_lx,carbon_c3drive_rt,
                   carbon_c3drive_lt,!!carbon_c3drive_arrived,carbon_c3drive_done);
    }
    return 1;
}
