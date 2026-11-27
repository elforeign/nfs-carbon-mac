/* Main-queue GameController sink. Fake mode returns before framework access. */
#ifndef CARBON_PADFX_OUTPUT_TEST
#import <GameController/GameController.h>
#endif
#include "carbon_padfx.h"
static GCController *fx_owner[2];
static NSMutableSet<GCController *> *fx_detached, *fx_debt;
static CarbonPadfxFrame fx_sent[2];
static uint64_t fx_sent_at[2];
static uint64_t fx_applied_generation[2];
static struct { GCController *ctl; CarbonPadfxFrame frame; uint64_t token; int queued; } fx_pending[2];

static void fx_restore(GCController *ctl) {
    if (!ctl || ![ctl.extendedGamepad isKindOfClass:GCDualSenseGamepad.class]) return;
    if ([fx_detached containsObject:ctl]) {
        if (!fx_debt) fx_debt = [NSMutableSet new];
        [fx_debt addObject:ctl]; return;
    }
    GCDualSenseGamepad *g = (GCDualSenseGamepad *)ctl.extendedGamepad;
    carbon_padfx_count(FX_WRITE); [g.leftTrigger setModeOff];
    carbon_padfx_count(FX_WRITE); [g.rightTrigger setModeOff];
}
static void fx_apply(GCDualSenseAdaptiveTrigger *trigger, Trig t) {
    carbon_padfx_count(FX_WRITE);
    switch (t.mode) {
    case T_WEAPON: [trigger setModeWeaponWithStartPosition:t.a endPosition:t.b resistiveStrength:t.c]; break;
    case T_VIBRATION: [trigger setModeVibrationWithStartPosition:t.a amplitude:t.b frequency:t.c]; break;
    case T_POSITIONAL:
        if (@available(macOS 12.3, *)) {
            GCDualSenseAdaptiveTriggerPositionalResistiveStrengths s;
            memcpy(s.values, t.strength, sizeof t.strength);
            [trigger setModeFeedbackWithResistiveStrengths:s];
        } else [trigger setModeFeedbackWithStartPosition:.05f resistiveStrength:t.strength[3]];
        break;
    default: [trigger setModeOff]; break;
    }
}
void carbon_padfx_output(unsigned slot, void *controller, CarbonPadfxFrame frame, uint64_t token) {
    if (slot >= 2) return;
    if (carbon_padfx_fake()) {
        if (!carbon_padfx_lock(slot, token, 1)) return;
        for (int i = 0; i < 2; ++i) {
            int kind = frame.trigger[i].mode == T_OFF ? FX_OFF :
                frame.role[i] == PADBIND_ROLE_GAS ? FX_GAS :
                frame.role[i] == PADBIND_ROLE_BRAKE ? FX_BRAKE :
                frame.role[i] == PADBIND_ROLE_SHIFT ? FX_SHIFT : FX_OFF;
            carbon_padfx_count(kind);
        }
        carbon_padfx_unlock(); return;
    }
    GCController *ctl = (__bridge GCController *)controller;
    if (!ctl) return;
    if (!carbon_padfx_lock(slot, token, 1)) return;
    static int exit_hooked;
    if (!exit_hooked) { exit_hooked = 1; atexit(padfx_close); rumble_signals(); }
    fx_pending[slot].ctl = ctl; fx_pending[slot].frame = frame;
    int queued = fx_pending[slot].queued && fx_pending[slot].token == token;
    fx_pending[slot].token = token; fx_pending[slot].queued = 1;
    carbon_padfx_unlock();
    if (queued) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!carbon_padfx_lock(slot, token, 1)) return;
        GCController *target = fx_pending[slot].ctl;
        CarbonPadfxFrame latest = fx_pending[slot].frame;
        fx_pending[slot].queued = 0; fx_pending[slot].ctl = nil;
        if (![fx_detached containsObject:target]) {
            if (fx_owner[slot] != target) { fx_restore(fx_owner[slot]); fx_owner[slot] = target; fx_sent_at[slot] = 0; }
            GCDualSenseGamepad *g = [target.extendedGamepad isKindOfClass:GCDualSenseGamepad.class] ?
                (GCDualSenseGamepad *)target.extendedGamepad : nil;
            uint64_t now = host_ticks();
            if (g && (memcmp(&latest.trigger, &fx_sent[slot].trigger, sizeof latest.trigger) ||
                      now - fx_sent_at[slot] >= 1000000000ull || !fx_sent_at[slot])) {
                fx_apply(g.leftTrigger, latest.trigger[0]); fx_apply(g.rightTrigger, latest.trigger[1]);
                fx_sent[slot] = latest; fx_sent_at[slot] = now;
            }
            fx_applied_generation[slot] = token;
        }
        carbon_padfx_unlock();
    });
}
void carbon_padfx_release(uint64_t token) {
    if (carbon_padfx_fake()) {
        if (!carbon_padfx_lock(0, token, 0)) return;
        for (unsigned slot = 0; slot < 2; ++slot) { fx_pending[slot].queued = 0; fx_pending[slot].ctl = nil; }
        carbon_padfx_count(FX_OFF);
        carbon_padfx_unlock(); return;
    }
    void (^release)(void) = ^{
        if (!carbon_padfx_lock(0, token, 0)) return;
        for (unsigned slot = 0; slot < 2; ++slot) {
            if (fx_pending[slot].token < token) { fx_pending[slot].queued = 0; fx_pending[slot].ctl = nil; }
            if (fx_applied_generation[slot] < token) {
                fx_restore(fx_owner[slot]); fx_owner[slot] = nil; fx_sent_at[slot] = 0;
            }
        }
        carbon_padfx_unlock();
    };
    if ([NSThread isMainThread]) release();
    else {
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_main_queue(), ^{ release(); dispatch_semaphore_signal(done); });
        dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 200 * NSEC_PER_MSEC));
    }
}
void carbon_padfx_attach(void *controller, int connected) {
    if (carbon_padfx_fake()) return;
    GCController *ctl = (__bridge GCController *)controller;
    if (!ctl) return;
    void (^attach)(void) = ^{
        /* Notification order is preserved by the main queue. */
        if (!fx_detached) fx_detached = [NSMutableSet new];
        if (connected) {
            [fx_detached removeObject:ctl];
            if ([fx_debt containsObject:ctl]) { fx_restore(ctl); [fx_debt removeObject:ctl]; }
        } else {
            [fx_detached addObject:ctl];
            for (unsigned slot = 0; slot < 2; ++slot)
                if (fx_owner[slot] == ctl) { fx_restore(ctl); fx_owner[slot] = nil; fx_sent_at[slot] = 0; }
        }
    };
    if ([NSThread isMainThread]) attach(); else dispatch_async(dispatch_get_main_queue(), attach);
}
