/* Seed the native Audio Mode option before entry; its own update requests the
 * DAC mode. The executable digest in game_image.h binds this guest address. */
static void private_carbon_audio_setup(void) {
    const char *value = getenv("NFS_CARBON_SURROUND");
    if (!PRIVATE_CARBON_SKIPFE || (value && !strcmp(value, "0"))) return;
    M32(0x00A63E70) = 2;
}
