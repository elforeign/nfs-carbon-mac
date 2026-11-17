/* Select the imported dome through the native camera visibility row. */
#include "host.h"
#include "game_select.h"
#include <stdlib.h>

#if NFS_GAME == NFS_GAME_PRIVATE
extern int render_dump_active(void);

void carbon_skydome_draw(Cpu *c, void (*original)(Cpu *)) {
    const char *overlay = getenv("NFS_CARBON_TRACK_OVERLAY");
    uint32_t view = M32(c->esp + 4), mode = M32(c->esp + 8);
    uint32_t model = 0x00B77910u, current = M32(model + 8);
    if (overlay && *overlay && M32(0x00A99BBCu) == 6 &&
        M32(0x00A73358u) && view && mode && mode < 5 &&
        (current == 0xED85BA82u || current == 0x1F389568u)) {
        uint32_t camera = M32(view + 0x40);
        if (camera) {
            Cpu work = *c;
            work.esp -= 512;
            /* Same row lookup as 007A4900: this=B69CD0, camera XYZ at +40.
             * Rows contain a u16 count at +10 and u16 sections at +12.
             * The combined writer reserves 2100 for imported resources and
             * adds it to every imported row; native rows retain their bytes. */
            work.ecx = 0x00B69CD0u;
            uint32_t position = camera + 0x40;
            uint32_t row = call_guest(&work, 0x007A3290u, 1, &position);
            unsigned count = row ? M16(row + 0x10) : 0, imported = 0;
            for (unsigned i = 0; i < count && i < 384; ++i)
                imported |= M16(row + 0x12 + 2*i) == 2100;
            uint32_t key = imported ? 0x1F389568u : 0xED85BA82u;
            if (key != current && call_guest(&work, 0x0055DF00u, 1, &key)) {
                /* Native destruction preserves streaming links; initialization also
                 * transfers the scenery transform and clears its LOD owners. */
                work.ecx = model;
                call_guest(&work, 0x0055BF70u, 0, NULL);
                uint32_t init[] = {model, 0x00B76EC0u, key};
                call_guest(&work, 0x007AF7F0u, 3, init);
            }
            if (diag_on && render_dump_active())
                diag_event("skydome: path=global view=%u row=%u imported=%u gate=%08X key=%08X solid=%08X camera=%.6g,%.6g,%.6g",
                    mode, row ? M16(row + 0x0c) : 0, imported,
                    M32(0x00AB0A98u), M32(model + 8), M32(model + 12),
                    (double)MF32(position), (double)MF32(position + 4), (double)MF32(position + 8));
        }
    }
    original(c);
}
#endif
