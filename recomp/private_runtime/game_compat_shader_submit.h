{
    extern uint32_t *carbon_daynight_shader(const uint32_t *, uint32_t, uint32_t *);
    extern uint32_t *carbon_coat_shader(const uint32_t *, uint32_t, uint32_t *);
    uint32_t count = e->ntokens;
    uint32_t *original = e->tokens;
    uint32_t *daylight = carbon_daynight_shader(original,count,&e->ntokens);
    if (!daylight) daylight = carbon_coat_shader(original,count,&e->ntokens); /* disjoint programs */
    extern uint32_t *carbon_road_headlight_shader(const uint32_t *, uint32_t, const uint32_t *, uint32_t, uint32_t *);
    uint32_t *road = carbon_road_headlight_shader(original,count,daylight ? daylight : original,e->ntokens,&e->ntokens);
    if (road) { free(daylight); daylight = road; }
    if (daylight) e->tokens = daylight;
    compile_entry(e);
    e->tokens = original;
    e->ntokens = count;
    free(daylight);
}
