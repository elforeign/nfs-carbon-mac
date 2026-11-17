/* Main-queue GameController sink. Fake mode returns before framework access. */
#ifndef CARBON_PADFX_OUTPUT_TEST
#import <GameController/GameController.h>
#endif
#include "carbon_padfx.h"
static GCController *fx_owner;
static NSMutableSet<GCController *> *fx_detached, *fx_debt;
static CarbonPadfxFrame fx_sent;
static uint64_t fx_sent_at;
static uint64_t fx_applied_generation;
static struct { GCController *ctl; CarbonPadfxFrame frame; uint64_t token; int queued; } fx_pending;

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
void carbon_padfx_output(void *controller, CarbonPadfxFrame frame, uint64_t token) {
    if (carbon_padfx_fake()) {
        if (!carbon_padfx_lock(token, 1)) return;
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
    if (!carbon_padfx_lock(token, 1)) return;
    static int exit_hooked;
    if (!exit_hooked) { exit_hooked = 1; atexit(padfx_close); rumble_signals(); }
    fx_pending.ctl = ctl; fx_pending.frame = frame;
    int queued = fx_pending.queued && fx_pending.token == token;
    fx_pending.token = token; fx_pending.queued = 1;
    carbon_padfx_unlock();
    if (queued) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!carbon_padfx_lock(token, 1)) return;
        GCController *target = fx_pending.ctl;
        CarbonPadfxFrame latest = fx_pending.frame;
        fx_pending.queued = 0; fx_pending.ctl = nil;
        if (![fx_detached containsObject:target]) {
            if (fx_owner != target) { fx_restore(fx_owner); fx_owner = target; fx_sent_at = 0; }
            GCDualSenseGamepad *g = [target.extendedGamepad isKindOfClass:GCDualSenseGamepad.class] ?
                (GCDualSenseGamepad *)target.extendedGamepad : nil;
            uint64_t now = host_ticks();
            if (g && (memcmp(&latest.trigger, &fx_sent.trigger, sizeof latest.trigger) ||
                      now - fx_sent_at >= 1000000000ull || !fx_sent_at)) {
                fx_apply(g.leftTrigger, latest.trigger[0]); fx_apply(g.rightTrigger, latest.trigger[1]);
                fx_sent = latest; fx_sent_at = now;
            }
            fx_applied_generation = token;
        }
        carbon_padfx_unlock();
    });
}
void carbon_padfx_release(uint64_t token) {
    if (carbon_padfx_fake()) {
        if (!carbon_padfx_lock(token, 0)) return;
        fx_pending.queued = 0; fx_pending.ctl = nil;
        carbon_padfx_count(FX_OFF);
        carbon_padfx_unlock(); return;
    }
    void (^release)(void) = ^{
        if (!carbon_padfx_lock(token, 0)) return;
        if (fx_pending.token < token) { fx_pending.queued = 0; fx_pending.ctl = nil; }
        if (fx_applied_generation < token) {
            fx_restore(fx_owner); fx_owner = nil; fx_sent_at = 0;
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
    void (^attach)(void) = ^{
        /* Notification order is preserved by the main queue. */
        GCController *target = ctl ? ctl : (!connected ? fx_owner : nil);
        if (!target) return;
        if (!fx_detached) fx_detached = [NSMutableSet new];
        if (connected) {
            [fx_detached removeObject:target];
            if ([fx_debt containsObject:target]) { fx_restore(target); [fx_debt removeObject:target]; }
        } else {
            [fx_detached addObject:target];
            if (fx_owner == target) { fx_restore(target); fx_owner = nil; fx_sent_at = 0; }
        }
    };
    if ([NSThread isMainThread]) attach(); else dispatch_async(dispatch_get_main_queue(), attach);
}
