#pragma once
#include "host.h"

/* Rectangles use x,y,width,height in main-target pixels. Captures have no rect. */
int carbon_splitworld_rect(uint32_t view, uint32_t rect[4]);
void carbon_splitworld_frame(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_layout(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_submit(Cpu *c, void (*original)(Cpu *));
void carbon_splitworld_bind(Cpu *c, void (*original)(Cpu *));
