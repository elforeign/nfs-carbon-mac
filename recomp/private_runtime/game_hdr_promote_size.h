    /* Smaller targets are eligible by decoded identity, never by size alone. */
    if(!float_scene_on || carbon_hdr_class(dst)<0)return;
    format=MTLPixelFormatRGBA16Float;
    NSUInteger w=g->tex.width,h=g->tex.height;
