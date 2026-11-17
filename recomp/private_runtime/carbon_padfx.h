#pragma once
#include <stdint.h>

enum { T_OFF, T_FEEDBACK, T_SLOPE, T_WEAPON, T_VIBRATION, T_POSITIONAL };
typedef struct { int mode; float a, b, c, d; float strength[10]; } Trig;
typedef struct { Trig trigger[2]; int role[2], breaker; float charge; } CarbonPadfxFrame;
enum { FX_MOTOR, FX_GAS, FX_BRAKE, FX_SHIFT, FX_OFF, FX_BREAKER, FX_OPEN, FX_WRITE, FX_COUNT };
int carbon_padfx_fake(void);
void carbon_padfx_count(int kind);
void carbon_padfx_counts(uint64_t out[FX_COUNT]);
void carbon_padfx_log(int force);
void carbon_padfx_output(void *controller, CarbonPadfxFrame frame, uint64_t token);
void carbon_padfx_release(uint64_t token);
void carbon_padfx_attach(void *controller, int connected);
/* A successful lock protects the final generation/freshness check through the sink. */
int carbon_padfx_lock(uint64_t token, int active);
void carbon_padfx_unlock(void);
