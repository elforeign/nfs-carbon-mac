/* Bounded, observational FE/load reader on the guest frame thread. */
#include "host.h"
#include "blackbox.h"
#include <stdlib.h>
#include "carbon_fe_probe.h"

static int carbon_fe_ok(uint32_t a) { return a >= 0x1000u && a < 0xFFFFF000u; }
static void carbon_fe_name(char out[32], uint32_t a) {
    unsigned n = 0;
    if (carbon_fe_ok(a)) for (; n < 31; ++n) {
        unsigned ch = M8(a + n);
        if (ch < 0x20 || ch >= 0x7F) break;
        out[n] = (char)ch;
    }
    out[n] = 0;
}
static void carbon_fe_manager(CarbonFEManager *m, uint32_t address, unsigned index) {
    BlackboxFE *v = &m->value;
    v->index = index;
    v->address = address;
    if (!carbon_fe_ok(address)) return;
    m->valid = 1;
    v->vtable = M32(address); v->state = M32(address + 4); v->start = M32(address + 8);
    v->previous = M32(address + 0x14); v->pending = M8(address + 0xA0);
    v->wait = M32(address + 0xA4); v->child = M32(address + 0xB0);
    carbon_fe_name(m->screen, address + 0x1C);
    carbon_fe_name(m->next, M32(address + 0x9C));
}
static void carbon_fe_read(CarbonFEState *s) {
    uint32_t address = M32(0x00A97A7Cu);
    for (unsigned i = 0; i < 3; ++i) {
        carbon_fe_manager(&s->manager[i], address, i);
        address = s->manager[i].value.child;
    }
    uint32_t mask = M32(0x00A9970Cu), garage = M32(0x00BBAA8Cu);
    s->load.mask = s->load.garage_ready = UINT32_MAX;
    if (carbon_fe_ok(mask)) {
        mask = M32(mask);
        if (carbon_fe_ok(mask)) { s->load.mask = M32(mask); s->load_valid |= 1; }
    }
    s->load.busy = M32(0x00B70650u + 0x1F0);
    s->load.want = M32(0x00B70650u + 0x32C);
    s->load.have = M32(0x00B70650u + 0x28);
    s->load.queued = M32(0x00B70650u + 0x24);
    s->load_valid |= 2;
    if (carbon_fe_ok(garage)) { s->load.garage_ready = M32(garage + 0x4C); s->load_valid |= 4; }
    uint32_t wrapper = M32(0x00A97A78u), engine = carbon_fe_ok(wrapper) ? M32(wrapper) : 0;
    uint32_t p = carbon_fe_ok(engine) ? M32(engine + 0xE4) : 0;
    for (; carbon_fe_ok(p) && s->count < CARBON_FE_PACKAGES; p = M32(p + 8)) {
        CarbonFEPackage *pkg = &s->package[s->count++];
        pkg->address = p; pkg->control = M32(p + 0x20);
        carbon_fe_name(pkg->name, M32(p + 0xC));
    }
    s->truncated = carbon_fe_ok(p);
}
void carbon_blackbox_fe(uint64_t frame, uint32_t flow, uint64_t now) {
    static CarbonFEState last;
    static int have;
    int record = blackbox_enabled(), mirror = carbon_fe_probe_enabled();
    if (!record && !mirror) return;
    CarbonFEState state = {0};
    carbon_fe_read(&state);
    if (record) {
        for (unsigned i = 0; i < 3; ++i) {
            CarbonFEManager *m = &state.manager[i];
            if (!have || memcmp(m, &last.manager[i], sizeof *m)) {
                BlackboxFE value = m->value;
                value.screen = blackbox_fe_label(m->screen);
                value.next = blackbox_fe_label(m->next);
                blackbox_record_fe(&value, m->valid, frame, now);
            }
        }
        if (!have || state.load_valid != last.load_valid || memcmp(&state.load, &last.load, sizeof state.load))
            blackbox_record_load(&state.load, state.load_valid, frame, now);
        if (!have || state.count != last.count || state.truncated != last.truncated ||
            memcmp(state.package, last.package, sizeof state.package)) {
            const CarbonFEPackage *control = NULL;
            for (unsigned i = 0; i < state.count; ++i)
                if (state.package[i].control) { control = &state.package[i]; break; }
            blackbox_record_package(control ? blackbox_fe_label(control->name) : 0,
                                    control ? control->address : 0, state.count, state.truncated, frame, now);
        }
        last = state;
        have = 1;
    }
    if (mirror) carbon_fe_probe(&state, flow);
}
