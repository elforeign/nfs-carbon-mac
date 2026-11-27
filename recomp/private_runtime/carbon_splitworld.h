#pragma once
#include "host.h"

/* Rectangles use x,y,width,height in main-target pixels. Captures have no rect. */
int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]);
void carbon_splitworld_frame(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_layout(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_submit(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_bind(Cpu *c, void (*original)(Cpu *));
int carbon_splitworld_position(uint32_t view, float position[3]);
uint32_t carbon_splitworld_effect_view(void);
int carbon_splitworld_dispatch_done(void);
int carbon_spliteffects_begin(uint32_t view);
void carbon_spliteffects_end(uint32_t view);
void carbon_spliteffects_reset(void);
void carbon_splitworld_update(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_auxiliary(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_weather(Cpu *c, void (*original)(Cpu *));
