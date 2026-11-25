// Primary scene adapter, isolated from the other renderer's camera state.
#pragma once
static int rt_scene_private_program(uint64_t shader) {
    // Decoded SM3 WORLDREFLECT: POSITION v0; dp4 clip.xyzw with c0..c3.
    return shader == 0x932f3e4ad7bf792dull;
}
static int rt_scene_guest_active(void) { return M32(0x00A99BBCu) == 6; }
static int rt_scene_guest_view(RTSceneView *view) {
    if (!rt_scene_guest_active()) return 0;
    Obj *color = obj(dev.rt[0]), *depth = obj(dev.ds);
    uint32_t owner = color && color->parent ? color->parent : dev.rt[0];
    uint32_t zowner = depth && depth->parent ? depth->parent : dev.ds;
    if (owner != M32(0x00AB04F4u) || zowner != M32(0x00AB04F8u)) return 0;
    uint32_t platform = M32(0x00B4AF90u);
    if (!platform) return 0;
    view->view = 1;
    memcpy(view->vp, G + platform + 0x80, sizeof view->vp);
    return 1;
}

#ifdef RT_SCENE_TEST
static void rt_scene_fixture_camera(uint32_t platform) {
    M32(0x00A99BBCu)=6; M32(0x00AB04F4u)=dev.rt[0]; M32(0x00AB04F8u)=dev.ds;
    M32(0x00B4AF90u)=platform;
}
static void rt_scene_fixture_inactive(void) { M32(0x00A99BBCu)=0; }
#endif
