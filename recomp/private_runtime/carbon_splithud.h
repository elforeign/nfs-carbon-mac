#pragma once
#include "host.h"

/* The authored packages use full-output coordinates, with 240 units per half.
 * x/y scale and homogeneous x/y translation; zero means the shared FE path. */
int carbon_splithud_transform(float transform[4]);
void carbon_splithud_clip(Cpu *c);
void carbon_splithud_draw(Cpu *c, void (*original)(Cpu *));
void carbon_splithud_probe_type(Cpu *c, void (*original)(Cpu *));
void carbon_splithud_probe_load(Cpu *c, void (*original)(Cpu *));
void carbon_splithud_probe_update(Cpu *c, void (*original)(Cpu *));
void carbon_splithud_probe_destroy(Cpu *c, void (*original)(Cpu *));
