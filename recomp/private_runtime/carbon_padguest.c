#include "host.h"
#include "carbon_padguest.h"

/* Native calls borrow neither the caller's registers nor its live stack. */
static uint32_t carbon_padguest_call(Cpu *c, uint32_t address, uint32_t self,
                                      unsigned n, const uint32_t *args) {
    Cpu q = *c;
    q.ecx = self;
    q.esp -= 64 + 4 * n;
    return call_guest(&q, address, n, args);
}

void carbon_padguest_backend(Cpu *c, void (*original)(Cpu *)) {
    uint32_t caller = M32(c->esp), io = c->esi;
    original(c);
    if (pad_count() != 2 || caller != 0x006892F0u || M32(io + 4) != 1) return;
    /* Reserve slot 1 on failure too. The native initializer then assigns
     * mouse/keyboard slots 2/3 and tears down every allocated slot normally. */
    M32(io + 12) = M32(io + 16) = M32(io + 20) = 0;
    uint32_t args[] = {1};
    uint32_t device = carbon_padguest_call(c, 0x006893D0u, 0, 1, args);
    if (device) {
        carbon_padguest_call(c, M32(M32(device) + 12), device, 0, NULL);
        M32(io + 12) = device;
        M32(io + 0x48) |= 2;
    }
    M32(io + 4) = 2;
    if (diag_on) diag_event("padguest device port=1 device=%08X", device);
}

void carbon_padguest_initialize(Cpu *c, void (*original)(Cpu *)) {
    uint32_t device = c->ecx;
    if (pad_count() != 2 || M32(device + 0x24) != 1) { original(c); return; }
    /* The native constructor sets these inline pointers only for the first
     * GameDevice. Initialize the guest's own storage before exposing rows. */
    M32(device + 0x18) = device + 0x34;
    M32(device + 0x1C) = device + 0x1034;
    M32(device + 0x20) = device + 0x1434;
    memset(G + device + 0x1034, 0, 0x800);
    M8(device + 0x183C) = 0;
    M32(device + 0x1840) = 1;
    M32(device + 0x1844) = M32(device + 0x1848) = M32(device + 0x184C) = 0;
    M8(device + 0x1850) = 0;
    /* Port 0 owns shared DirectInput/default initialization and polling. */
    for (unsigned a = 0; a < 72; ++a) {
        uint32_t row = M32(device + 0x18) + 16 * a;
        uint32_t name[] = {M32(0x00A98700u + 8 * a)};
        M32(row) = 1;
        M32(row + 4) = carbon_padguest_call(c, 0x00606B60u, 0, 1, name);
        M32(row + 8) = M32(device + 0x1C) + 4 * a;
        M32(row + 12) = M32(device + 0x20) + 4 * a;
    }
    M32(device + 0x1838) = 72;
    c->esp += 4;
}

void carbon_padguest_evaluate(Cpu *c, void (*original)(Cpu *)) {
    uint32_t device = c->ecx, port = M32(device + 0x24);
    if (pad_count() != 2 || port > 1 || !M32(0x00AB0AD0u) || M8(device + 0x183C)) {
        original(c); return;
    }
    if (!port) {
        /* Preserve native mouse/key edges and wheel logic, but keep guest pad
         * bindings out of its maxima and side effects. Restore before padbind. */
        uint32_t saved[72][32];
        unsigned count = M32(0x00A98948u);
        if (count > 16) { original(c); return; }
        for (unsigned a = 0; a < 72; ++a) {
            for (unsigned p = 0; p < count; ++p) {
                uint32_t physical = M32(0x00A986D0u + 4 * p);
                uint32_t row = M32(0x00A98704u + 8 * a) + 12 * (2 + 2 * p);
                saved[a][2*p] = M32(row); saved[a][2*p+1] = M32(row + 12);
                if (p || !physical || physical == 0xFFFFFFFCu) M32(row) = M32(row + 12) = 0;
            }
        }
        original(c);
        for (unsigned a = 0; a < 72; ++a) for (unsigned p = 0; p < count; ++p) {
            uint32_t row = M32(0x00A98704u + 8 * a) + 12 * (2 + 2 * p);
            M32(row) = saved[a][2*p]; M32(row + 12) = saved[a][2*p+1];
        }
        return;
    }
    original(c); /* native port-1 evaluator is inert; retain its ABI */
    uint32_t output = M32(device + 0x20), previous = M32(device + 0x1C);
    if (!output || !previous) return;
    memcpy(G + previous, G + output, 0x400);
    memset(G + output, 0, 0x400);
    if (!M32(0x00A986F4u) || M32(0x00A98948u) < 2) return;
    uint32_t physical = M32(0x00A986D4u);
    if (!physical || physical == 0xFFFFFFFCu) return;
    for (unsigned a = 0; a < 72; ++a) {
        float value = 0;
        for (unsigned slot = 4; slot < 6; ++slot) {
            uint32_t row = M32(0x00A98704u + 8 * a) + 12 * slot;
            if (M32(row) <= 1) continue; /* keyboard belongs to port 0 */
            Cpu q = *c;
            q.esp -= 64;
            uint32_t args[] = {a, slot};
            call_guest(&q, 0x0067A340u, 2, args);
            value = fmaxf(value, (float)q.st[q.top]);
        }
        MF32(output + 4 * a) = value;
    }
}

static uint32_t carbon_padguest_fe, carbon_padguest_second;
uint32_t carbon_padguest_queue(uint32_t fe, unsigned port) {
    if (!fe || port > 1) return 0;
    return port ? (fe == carbon_padguest_fe ? carbon_padguest_second : 0) : M32(fe);
}

static void carbon_padguest_dispose(Cpu *c) {
    uint32_t q = carbon_padguest_second;
    carbon_padguest_second = 0;
    carbon_padguest_fe = 0;
    if (!q) return;
    carbon_padguest_call(c, 0x006959A0u, q, 0, NULL);
    uint32_t args[] = {q, 0x29C, 0};
    carbon_padguest_call(c, 0x00609E80u, 0x00A99720u, 3, args);
}

void carbon_padguest_construct(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    carbon_padguest_dispose(c);
    uint32_t fe = c->ecx;
    M32(fe) = M32(fe + 4) = M32(fe + 8) = 0;
    M32(fe + 12) = 0x82D21520u;
    carbon_padguest_fe = fe;
    for (unsigned p = 0; p < 2; ++p) {
        if (p && !M32(0x00A991E4u)) continue;
        uint32_t alloc[] = {0x29C, 0};
        uint32_t q = carbon_padguest_call(c, 0x0060BA70u, 0x00A99720u, 2, alloc);
        if (!q) continue;
        uint32_t args[] = {p, M32(fe + 12), 0x009D0550u, 0};
        carbon_padguest_call(c, 0x00696D30u, q, 4, args);
        if (p) carbon_padguest_second = q; else M32(fe) = q;
        uint32_t on[] = {1};
        carbon_padguest_call(c, 0x00694A50u, q, 1, on);
        carbon_padguest_call(c, 0x00678900u, q, 0, NULL);
        if (diag_on) diag_event("padguest queue port=%u device=%08X queue=%08X", p,
                               M32(0x00A991E0u + 4 * p), q);
    }
    c->eax = fe;
    c->esp += 4;
}

void carbon_padguest_destroy(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() == 2 && c->ecx == carbon_padguest_fe) carbon_padguest_dispose(c);
    original(c);
}

void carbon_padguest_connected(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    uint32_t q = carbon_padguest_queue(c->ecx, arg(c, 0));
    c->eax = q ? carbon_padguest_call(c, 0x00678900u, q, 0, NULL) : 0;
    c->esp += 8;
}

/* Carbon's queue connection sampler calls the logical device's +18 vmethod. */
void carbon_padguest_device_connected(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2 || M32(c->ecx + 0x24) != 1) { original(c); return; }
    PadState state = {0};
    pad_read_n(1, &state);
    c->eax = (c->eax & ~0xFFu) | !!state.connected;
    c->esp += 4;
}

static void carbon_padguest_set_enabled(Cpu *, uint32_t, unsigned, int, int);

static void carbon_padguest_connect_event(Cpu *c, uint32_t fe, unsigned port) {
    uint32_t db = M32(0x00A97A7Cu);
    if (!db || !M32(db + 0xCC)) return;
    Cpu read = *c;
    uint32_t out = read.esp - 16;
    M32(out) = 0;
    uint32_t args[] = {0xBC7, out, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu};
    carbon_padguest_call(&read, 0x004A0490u, 0x00A8AD30u, 5, args);
    int two = M32(out) || carbon_padguest_call(c, 0x0075CF70u, 0, 0, NULL) == 1;
    unsigned p0 = M8(M32(db + 0xCC)), p1 = M8(M32(db + 0xCC) + 1);
    if (two && port == p0 && p1 != 0xFF) carbon_padguest_set_enabled(c, fe, p1, 1, 0);
    else if (two && port == p1 && p0 != 0xFF) carbon_padguest_set_enabled(c, fe, p0, 1, 0);
    carbon_padguest_set_enabled(c, fe, port, 1, 0);
}

/* 0059FF46..77 rounds action magnitude through the native x87 converter
 * into each column's integer button value. */
static uint32_t carbon_padguest_value(Cpu *c, uint32_t event) {
    Cpu q = *c;
    q.esp -= 64;
    x87_push(&q, event ? (double)MF32(event + 8) : 0.0);
    q.st[q.top] = x87_round(&q, q.st[q.top] + (double)MF32(0x009C2888u));
    return call_guest(&q, 0x0087EAC0u, 0, NULL);
}

void carbon_padguest_events(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    uint32_t fe = c->ecx;
    for (unsigned p = 0; p < 2; ++p) {
        uint32_t q = carbon_padguest_queue(fe, p);
        if (!q) continue;
        while (!(carbon_padguest_call(c, 0x00680310u, q, 0, NULL) & 0xFF)) {
            uint32_t scratch = c->esp - 16;
            M32(scratch) = 0;
            uint32_t args[] = {scratch};
            carbon_padguest_call(c, 0x00680350u, q, 1, args);
            uint32_t event = M32(scratch);
            if (event && M32(event) == 0x89) carbon_padguest_connect_event(c, fe, p);
            else {
                int connected = carbon_padguest_call(c, 0x00678900u, q, 0, NULL) & 0xFF;
                for (unsigned row = 0; row < 16; ++row) {
                    uint32_t map = 0x00A5E038u + 28 * row;
                    if (!connected) M32(map + 12 + 4*p) = 0;
                    else if (event && M32(map) == M32(event)) {
                        M32(map + 12 + 4*p) = carbon_padguest_value(c, event);
                        /* Native shared frontend shortcuts remain P1-owned. */
                        if (!p && !(carbon_padguest_call(c, M32(M32(0x00A604B8u)),
                                                       0x00A604B8u, 0, NULL) & 0xFF)) {
                            if (M32(event) == 0x37 && MF32(event + 8) == 1.0f)
                                carbon_padguest_call(c, 0x00598800u, 0, 0, NULL);
                            else if (M32(event) == 0x38) {
                                uint32_t db = M32(0x00A97A7Cu);
                                if (db) M8(db + 0xE4) = MF32(event + 8) == 1.0f;
                            }
                        }
                        break;
                    }
                }
            }
            carbon_padguest_call(c, 0x00680320u, q, 0, NULL);
        }
    }
    c->esp += 4;
}

void carbon_padguest_required(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    uint32_t fe = c->ecx, db = M32(0x00A97A7Cu);
    if (!fe || !db || !M32(db + 0xCC)) { c->esp += 4; return; }
    uint32_t ports = M32(db + 0xCC);
    for (unsigned player = 0; player < 2; ++player) {
        unsigned port = M8(ports + player);
        if (port == 4) {
            for (unsigned p = 0; p < 2; ++p) {
                uint32_t q = carbon_padguest_queue(fe, p);
                if (q) M8(q + 0x28D) = 0;
            }
            M32(fe + 4) = M32(fe + 8) = 0;
        } else if (port < 2) {
            uint32_t q = carbon_padguest_queue(fe, port);
            if (q) M8(q + 0x28D) = M32(db + 0xC8) == 0xFFFFFFFFu;
            if (M32(db + 0xC8) != 0xFFFFFFFFu) {
                M8(fe + 4 + port) = 0;
                continue;
            }
            int connected = q && (carbon_padguest_call(c, 0x00678900u, q, 0, NULL) & 0xFF);
            if (connected) M8(fe + 4 + port) = 0;
            else if (M32(0x00A99BBCu) != 2 && M32(0x00A99BBCu) != 9) M8(fe + 4 + port) = 1;
        }
    }
    uint32_t guards = M32(0x00A97D84u), count = M32(0x00A97D8Cu);
    for (unsigned i = 0; i < count; ++i) {
        uint32_t object = M32(guards + 4*i);
        if (!object || !(carbon_padguest_call(c, M32(M32(object)), object, 0, NULL) & 0xFF)) {
            c->esp += 4; return;
        }
    }
    unsigned missing = 0;
    while (missing < 8 && !M8(fe + 4 + missing)) ++missing;
    if (missing == 8) { c->esp += 4; return; }
    uint32_t io = carbon_padguest_call(c, 0x00680510u, 0, 0, NULL);
    for (unsigned i = 0; io && i < M32(io + 4) && i < 16; ++i) {
        uint32_t device = M32(io + 8 + 4*i);
        if (device) carbon_padguest_call(c, M32(M32(device) + 0x20), device, 0, NULL);
    }
    uint32_t wrapper = M32(0x00A97A78u), engine = wrapper ? M32(wrapper) : 0;
    if (engine && engine != 0xFFFFFF28u) {
        uint32_t package = M32(engine + 0xE4);
        for (unsigned i = 0; package && i < 128; ++i, package = M32(package + 8)) {
            if (M32(package + 0x20)) {
                uint32_t args[] = {0x009D00FCu, M32(package + 12)};
                if (!carbon_padguest_call(c, 0x00471280u, 0, 2, args)) { c->esp += 4; return; }
                break;
            }
        }
    }
    if (!wrapper) { c->esp += 4; return; }
    M32(db + 0xC8) = missing == M8(ports + 1);
    uint32_t args[] = {0x009D00FCu, missing, missing};
    carbon_padguest_call(c, 0x005913C0u, wrapper, 3, args);
    c->esp += 4;
}

static void carbon_padguest_set_enabled(Cpu *c, uint32_t fe, unsigned port, int on, int flush) {
    unsigned first = port == 4 ? 0 : port, end = port == 4 ? 2 : port + 1;
    for (unsigned p = first; p < end && p < 2; ++p) {
        uint32_t q = carbon_padguest_queue(fe, p);
        if (!q) continue;
        if (on && (carbon_padguest_call(c, 0x00678960u, q, 0, NULL) & 0xFF)) continue;
        uint32_t args[] = {(uint32_t)on};
        carbon_padguest_call(c, 0x00694A50u, q, 1, args);
        if (flush) carbon_padguest_call(c, 0x006891E0u, q, 0, NULL);
    }
}
void carbon_padguest_enable(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    carbon_padguest_set_enabled(c, c->ecx, arg(c, 0), 1, arg(c, 1) & 0xFF);
    c->esp += 12;
}
void carbon_padguest_disable(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    carbon_padguest_set_enabled(c, c->ecx, arg(c, 0), 0, arg(c, 1) & 0xFF);
    c->esp += 12;
}
void carbon_padguest_enabled(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    unsigned port = arg(c, 0), first = port == 4 ? 0 : port, end = port == 4 ? 2 : port + 1;
    int enabled = first < 2;
    for (unsigned p = first; p < end && p < 2; ++p) {
        uint32_t q = carbon_padguest_queue(c->ecx, p);
        enabled &= q && (carbon_padguest_call(c, 0x00678960u, q, 0, NULL) & 0xFF);
    }
    c->eax = (c->eax & ~0xFFu) | enabled;
    c->esp += 8;
}

void carbon_padguest_enable_all(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    carbon_padguest_set_enabled(c, M32(0x00A97814u), 4, 1, 1);
    c->esp += 8;
}
void carbon_padguest_disable_all(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    carbon_padguest_set_enabled(c, M32(0x00A97814u), 4, 0, 1);
    c->esp += 4;
}
void carbon_padguest_queue_connected(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2 || c->ecx) { original(c); return; }
    c->eax &= ~0xFFu; c->esp += 4;
}
void carbon_padguest_queue_enabled(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2 || c->ecx) { original(c); return; }
    c->eax &= ~0xFFu; c->esp += 4;
}
void carbon_padguest_queue_toggle(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    uint32_t caller = M32(c->esp), self = c->ecx, on = arg(c, 0);
    if (self) original(c); else c->esp += 8;
    if (!carbon_padguest_fe || self != M32(carbon_padguest_fe)) return;
    /* Inlined all-port package transitions; individual queue calls stay local. */
    switch (caller) {
    case 0x00584151u: case 0x005BB48Cu:
        carbon_padguest_set_enabled(c, carbon_padguest_fe, 1, on & 0xFF, 0);
        break;
    }
}
void carbon_padguest_queue_flush(Cpu *c, void (*original)(Cpu *)) {
    if (pad_count() != 2) { original(c); return; }
    uint32_t caller = M32(c->esp), self = c->ecx;
    if (self) original(c); else c->esp += 4;
    if (!carbon_padguest_fe || self != M32(carbon_padguest_fe)) return;
    if (caller == 0x005840CAu || caller == 0x00584158u || caller == 0x005BB493u) {
        if (carbon_padguest_second)
            carbon_padguest_call(c, 0x006891E0u, carbon_padguest_second, 0, NULL);
        for (unsigned i = 0; i < 16; ++i) M32(0x00A5E048u + 28 * i) = 0;
    }
}
