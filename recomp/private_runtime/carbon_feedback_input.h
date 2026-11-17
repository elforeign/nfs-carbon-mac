/* Observe existing host activity without replacing its prompt/menu providers
 * or polling input again. Only the first pad drives this feedback model. */
#if NFS_GAME == NFS_GAME_PRIVATE
void carbon_feedback_input(int pad);
static void carbon_feedback_observe_input(int pad) {
    carbon_feedback_input(pad);
    prompts_input(pad);
}
static void carbon_feedback_observe_mouse(float points) {
    if (points > 0) carbon_feedback_input(0);
    prompts_mouse_moved(points);
}
static int carbon_feedback_observe_pad(int port, uint32_t buttons, int up, int down, int left, int right,
                                     float lx, float ly, int connected, int xbox) {
    if (port == 0) {
        if (!connected) carbon_feedback_input(0);
        else if (buttons || up || down || left || right || lx > .2f || lx < -.2f || ly > .2f || ly < -.2f)
            carbon_feedback_input(1);
    }
    return osk_pad(port, buttons, up, down, left, right, lx, ly, connected, xbox);
}
#define prompts_input carbon_feedback_observe_input
#define prompts_mouse_moved carbon_feedback_observe_mouse
#define osk_pad carbon_feedback_observe_pad
#endif
