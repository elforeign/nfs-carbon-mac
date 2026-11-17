#include "carbon_pad_layout.h"
/* The shared registry has no per-row reset callback. Keep its other rows on
 * the native reset path and route this private row through the shared helper. */
static void carbon_pad_layout_row_reset(Setting *row) {
    if (row && !strcmp(row->id,"controls.pad_layout")) {
        carbon_pad_layout_reset();
        row->saved = 0;
        row->value = carbon_pad_layout_get();
    } else settings_reset(row);
}
#define settings_reset carbon_pad_layout_row_reset
