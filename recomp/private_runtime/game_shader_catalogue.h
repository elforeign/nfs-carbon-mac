/* The catalogue runs before frames start. Compile lacquer off and both material
 * finishes, including lamp programs. Changing materials while lacquer is off
 * must not leave the next On toggle with an uncompiled finish. */
static void shader_preload_finish(Obj *s, const SmOptions *opt, uint32_t variant) {
    ShaderEntry *current = get_shader_variant(s, opt, variant);
    extern uint32_t carbon_coat_cache_variant(uint64_t, uint32_t);
    uint32_t selected = carbon_coat_cache_variant(s->tokens_hash, variant);
    const char *value = getenv("NFS_CARBON_COAT");
    char *saved = value ? strdup(value) : NULL;
    if (value && !saved) return;
    const char *materials = getenv("NFS_CARBON_MATERIALS");
    char *saved_materials = materials ? strdup(materials) : NULL;
    if (materials && !saved_materials) { free(saved); return; }
    for (int finish = 0; finish < 3; ++finish) {
        setenv("NFS_CARBON_COAT", finish ? "1" : "0", 1);
        setenv("NFS_CARBON_MATERIALS", finish == 2 ? "1" : "0", 1);
        uint32_t other = carbon_coat_cache_variant(s->tokens_hash, variant);
        if (other == selected) continue;
        uint64_t key = fnv(&current->opt, sizeof current->opt, s->tokens_hash);
        if (other) key = fnv(&other, 4, key);
        int have = 0;
        for (int i = 0; i < nshaders && !have; ++i) have = shaders[i]->key == key;
        if (!have) {
            ShaderEntry *e = new_entry(key, s->tokens, s->ntokens, &current->opt, variant);
            shader_submit(e);
            /* Both finishes persist the same untagged recipe; the selected
             * entry already wrote it. Do not append a duplicate every launch. */
        }
    }
    if (saved) { setenv("NFS_CARBON_COAT", saved, 1); free(saved); }
    else unsetenv("NFS_CARBON_COAT");
    if (saved_materials) { setenv("NFS_CARBON_MATERIALS", saved_materials, 1); free(saved_materials); }
    else unsetenv("NFS_CARBON_MATERIALS");
}

static void shader_preload_variant(Obj *s, const SmOptions *opt, uint32_t variant) {
    ShaderEntry e = {0}; e.tokens = s->tokens; e.ntokens = s->ntokens;
    e.opt = shader_options(shader_shape(s->tokens, s->ntokens, s->tokens_hash), opt); e.variant = variant;
    if (!sm_translate(e.tokens, e.ntokens, &e.opt, &e.refl)) {
        char *source = shader_replacement(&e);
        if (source) shader_preload_finish(s, opt, variant);
        free(source);
    }
    sm_result_free(&e.refl);
}
static void shader_preload_blob(const uint32_t *words, uint32_t count, const char *name) {
    if (count < 2 || words[0] != 0xFEFF0901u) return;
    int world = !strcmp(name, "IDI_WORLD_FX") || !strcmp(name, "IDI_WORLDNORMALMAP_FX");
    // Reflective-world draws can use the same additive AUX pass.
    int aux = world || !strcmp(name, "IDI_WORLDREFLECT_FX");
    for (uint32_t i = 2; i < count; ++i) {
        uint32_t v = words[i];
        if ((v >> 16 != 0xFFFE && v >> 16 != 0xFFFF) || ((v >> 8) & 255) < 1 || ((v >> 8) & 255) > 3 || (v & 255) > 4) continue;
        uint32_t n = (uint32_t)sm_token_count(words + i, count - i);
        if (!n) continue;
        Obj s = {0}; s.tokens = (uint32_t *)words + i; s.ntokens = n;
        s.tokens_hash = fnv(s.tokens, 4 * (size_t)n, 1469598103934665603ull);
        ShaderShape *shape = shader_shape(s.tokens, n, s.tokens_hash);
        if (shape) {
            SmOptions opt; sm_default_options(&opt);
            for (int shadow = 0; shadow <= (shape->shadow != 0); ++shadow) {
                opt.shadow_samplers = shadow ? shape->shadow : 0;
                shader_preload_finish(&s, &opt, 0);
                // Additive SSAO coverage can replay any embedded pixel program.
                // Prepare it at load, before a new light card or flare is drawn.
                if (v >> 16 == 0xFFFFu) shader_preload_variant(&s, &opt, MAT_VARIANT_AO_GLOW);
                if (world) for (uint32_t shell = 1; shell <= 10; ++shell) shader_preload_variant(&s, &opt, shell);
                if (aux) shader_preload_variant(&s, &opt, MAT_VARIANT_AUX);
                if (world) shader_preload_variant(&s, &opt, MAT_VARIANT_WATER);
                if (roadfilm_shader_hash(s.tokens_hash) && roadfilm_enabled())
                    shader_preload_variant(&s, &opt, MAT_VARIANT_ROAD_FILM);
                if (!strcmp(name, "IDI_CAR_FX") && realworld_materials_mode()) {
                    shader_preload_variant(&s, &opt, MAT_VARIANT_REAL_GLASS);
                    shader_preload_variant(&s, &opt, MAT_VARIANT_REAL_CHROME);
                }
                if (!strcmp(name, "IDI_CAR_FX")) { shader_preload_variant(&s, &opt, MAT_VARIANT_CARBON_LAMP); shader_preload_variant(&s, &opt, MAT_VARIANT_HEADLAMP_CLEAR); }
                if (!strcmp(name, "IDI_CAR_FX") && clearcoat_shader_hash(s.tokens_hash)) shader_preload_variant(&s, &opt, MAT_VARIANT_CLEARCOAT);
                if (!strcmp(name, "IDI_GLOSSYWINDOW_FX")) shader_preload_variant(&s, &opt, MAT_VARIANT_GLASS);
                if (!strcmp(name, "IDI_TREE_FX")) shader_preload_variant(&s, &opt, MAT_VARIANT_TREES);
                if (!strcmp(name, "IDI_WORLDBONE_FX")) shader_preload_variant(&s, &opt, MAT_VARIANT_BONE);
                if (!strcmp(name, "IDI_PARTICLES_FX")) {
                    shader_preload_variant(&s, &opt, MAT_VARIANT_SOFT_SMOKE);
                    shader_preload_variant(&s, &opt, MAT_VARIANT_SOFT_SMOKE_RESOLVED);
                    shader_preload_variant(&s, &opt, MAT_VARIANT_SOFT_SMOKE_LATE);
                }
            }
        }
        i += n - 1;
    }
}
static void shader_catalogue_warm(void) {
    // Same trusted PE resource walk as d3dx_effect.c: RT_RCDATA -> name -> language -> data.
    uint32_t pe = 0x400000 + M32(0x40003C);
    uint32_t rsrc = 0x400000 + M32(pe + 24 + 96 + 2 * 8);
    if (rsrc == 0x400000) return;
    int before = nshaders;
    uint32_t count = M16(rsrc + 12) + M16(rsrc + 14);
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t id = M32(rsrc + 16 + 8 * i), off = M32(rsrc + 20 + 8 * i);
        if (id != 10 || !(off & 0x80000000)) continue;
        uint32_t d2 = rsrc + (off & 0x7FFFFFFF), n2 = M16(d2 + 12) + M16(d2 + 14);
        for (uint32_t k = 0; k < n2; ++k) {
            uint32_t nid = M32(d2 + 16 + 8 * k), o2 = M32(d2 + 20 + 8 * k);
            if (!(nid & 0x80000000)) continue;
            uint32_t str = rsrc + (nid & 0x7FFFFFFF), len = M16(str);
            char name[128]; uint32_t q = 0;
            for (; q < len && q < sizeof name - 1; ++q) name[q] = (char)M16(str + 2 + 2 * q);
            name[q] = 0;
            uint32_t d3 = rsrc + (o2 & 0x7FFFFFFF);
            if (o2 & 0x80000000) d3 = rsrc + (M32(d3 + 20) & 0x7FFFFFFF);
            uint32_t va = 0x400000 + M32(d3), bytes = M32(d3 + 4);
            shader_preload_blob((const uint32_t *)(G + va), bytes / 4, name);
        }
    }
    if (diag_on) diag_event("shader_compile: preloaded=%d frame_sync=%llu", nshaders - before, stat_sync_shader);
}

