#pragma once
/* Carbon has three choices; the shared two-choice API retains its boolean contract. */
typedef enum { CARBON_LAYOUT_PLAYSTATION, CARBON_LAYOUT_XBOX, CARBON_LAYOUT_PC } CarbonPadLayout;
typedef enum { CARBON_LAYOUT_AUTOMATIC, CARBON_LAYOUT_APP, CARBON_LAYOUT_ENV } CarbonPadLayoutOrigin;
typedef struct { CarbonPadLayout layout; CarbonPadLayoutOrigin origin; int kind; } CarbonPadLayoutChoice;
int carbon_pad_layout_parse(const char *token);
CarbonPadLayoutChoice carbon_pad_layout_resolve(unsigned pad);
const char *carbon_pad_layout_name(CarbonPadLayout layout);
const char *carbon_pad_layout_origin(CarbonPadLayoutOrigin origin);
int carbon_pad_layout_get(void);
void carbon_pad_layout_set(int value);
void carbon_pad_layout_reset(void);
void carbon_pad_layout_reason(char *buffer, int size);
void carbon_pad_layout_menu_init(void);
