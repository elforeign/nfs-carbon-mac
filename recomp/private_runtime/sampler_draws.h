/* Inside the selected draw dump: no work or state changes outside sampled frames.
 * Include bound-but-unused stages explicitly; shader reflection identifies reads.
 * Vertex texture registers use device slots 16..19, pixel registers 0..15. */
{
    for (unsigned slot = 0; slot < 20; ++slot) {
        const SmResult *reflection = slot < 16 ? &pse->refl : &vse->refl;
        unsigned reg = slot < 16 ? slot : slot - 16;
        int sampled = 0;
        for (int k = 0; k < reflection->n_samplers; ++k)
            if (reflection->samplers[k].reg == reg) sampled = 1;
        if (!sampled && !dev.tex[slot]) continue;
        Obj *texture = obj(dev.tex[slot]);
        RenderTex *gpu = texture ? texture->gpu : NULL;
        const uint32_t *state = dev.ss[slot];
        float bias;
        memcpy(&bias, &state[8], sizeof bias);
        fprintf(df, "  sampler %s%u read=%d tex=%08X kind=%d size=%ux%ux%u levels=%u gpu_levels=%lu "
                "min=%u mag=%u mip=%u aniso=%u bias=%.9g bias_bits=%08X maxmip=%u addr=%u,%u,%u\n",
                slot < 16 ? "ps" : "vs", reg, sampled, dev.tex[slot], texture ? texture->kind : 0,
                texture ? texture->w : 0, texture ? texture->h : 0, texture ? texture->d : 0,
                texture ? texture->levels : 0, (unsigned long)(gpu ? gpu->tex.mipmapLevelCount : 0),
                state[6], state[5], state[7], state[10], bias, state[8], state[9], state[1], state[2], state[3]);
    }
}
