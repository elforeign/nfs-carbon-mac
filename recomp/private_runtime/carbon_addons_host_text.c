/* Native text-field adapter. Only the guest thread reads fields or invokes methods. */
#include "host.h"
#include "onscreen_keyboard.h"
#include <string.h>

enum { TEXT_HOST = 0x00A604B8u };
static uint64_t text_epoch;
static uint64_t allowed_epoch = UINT64_MAX;
static uint32_t allowed_field, allowed_type;
static uint8_t allowed_characters[256];
void carbon_addons_host_text_restart(void);
uint32_t call_guest(Cpu *, uint32_t, int, const uint32_t *);

/* 005C51B0 creates the edit field at +27C. Its paired native accept/cancel
 * methods clear it after publishing their normal frontend notifications. */
void carbon_addons_host_text_begin(Cpu *c, void (*original)(Cpu *)) {
    if (c->ecx == TEXT_HOST) {
        ++text_epoch;
        carbon_addons_host_text_restart();
    }
    original(c);
}
static uint32_t text_call(Cpu *c, uint32_t function, uint32_t self, unsigned n, const uint32_t *args) {
    Cpu copy = *c;
    copy.ecx = self;
    return call_guest(&copy, function, (int)n, args);
}
int carbon_addons_host_text_snapshot(Cpu *c, OskCapture *out) {
    uint32_t field = M32(TEXT_HOST + 0x27C);
    if (!field) return 0;
    memset(out, 0, sizeof *out);
    out->active = 1; out->target = field; out->generation = text_epoch;
    out->owner = osk_last_pad(); out->player = 0;
    out->type = M32(field + 4);
    unsigned limit = M32(field + 0x10);
    out->limit = limit < 155 ? limit : 155;
    if (allowed_field != field || allowed_epoch != text_epoch || allowed_type != out->type) {
        memset(allowed_characters, 0, sizeof allowed_characters);
        for (unsigned ch = 32; ch < 256; ++ch)
            allowed_characters[ch] = text_call(c, 0x00570340u, field, 1, &ch) & 0xFF;
        allowed_field = field; allowed_epoch = text_epoch; allowed_type = out->type;
    }
    memcpy(out->allowed, allowed_characters, sizeof out->allowed);
    uint32_t wide = M32(field + 8);
    if (!wide) return 0;
    size_t bytes = 0;
    /* +1C is the cursor, not the length. The native buffer has 156 UTF-16 units. */
    for (unsigned i = 0; i < 155 && M16(wide + 2*i); ++i) {
        unsigned ch = out->type == 2 ? '*' : M16(wide + 2*i);
        if (ch < 128) out->text[bytes++] = (char)ch;
        else if (ch < 2048) { out->text[bytes++] = (char)(0xC0 | ch >> 6); out->text[bytes++] = (char)(0x80 | (ch & 63)); }
        else { out->text[bytes++] = (char)(0xE0 | ch >> 12); out->text[bytes++] = (char)(0x80 | ((ch >> 6) & 63)); out->text[bytes++] = (char)(0x80 | (ch & 63)); }
        ++out->length;
    }
    out->text[bytes] = 0;
    return 1;
}
void carbon_addons_host_text_event(Cpu *c, uint32_t target, int action, unsigned ch) {
    if (!target || M32(TEXT_HOST + 0x27C) != target) return;
    if (action == OSK_ACCEPT || action == OSK_CANCEL) {
        text_call(c, action == OSK_ACCEPT ? 0x005A00B0u : 0x005A0030u, TEXT_HOST, 0, NULL);
        return;
    }
    if (action == OSK_CLEAR) {
        /* Native End moves to the end before native Backspace removes the text. */
        text_call(c, 0x005BAD00u, TEXT_HOST, 0, NULL);
        ch = 8;
        for (unsigned i = 0; i < 155 && M32(TEXT_HOST + 0x27C) == target && M32(target + 0x1C); ++i) {
            unsigned before = M32(target + 0x1C);
            text_call(c, 0x005C5260u, TEXT_HOST, 1, &ch);
            if (M32(TEXT_HOST + 0x27C) != target || M32(target + 0x1C) >= before) break;
        }
    } else if (action == OSK_TYPE || action == OSK_DELETE) {
        if (action == OSK_DELETE) ch = 8;
        text_call(c, 0x005C5260u, TEXT_HOST, 1, &ch);
    }
}
