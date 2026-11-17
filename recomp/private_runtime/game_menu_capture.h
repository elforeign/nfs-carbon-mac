    if (is_open && diag_on && last_ctx && diag_shot_due(dev.frames) == 2) {
        char path[1024];
        snprintf(path, sizeof path, "%s/menu_%05llu.png", diag_dir, (unsigned long long)dev.frames);
        diag_png(path, CGBitmapContextGetData(last_ctx), (uint32_t)last_w, (uint32_t)last_h, (uint32_t)CGBitmapContextGetBytesPerRow(last_ctx), 1);
        CGSize v = layer.bounds.size;
        diag_event("menu: capture %s (panel %zux%zu in a %.0fx%.0f pt view, tab %s, row %d)", path, last_w, last_h, v.width, v.height,
                   settings_category_names[tab], sel);
    }
