/* Fixed disabled feature boundary. Changes require declaration/initializer review.
 * The build rejects any dependency outside this inventory; it never invents stubs.
 */
#include "render_internal.h"
#include "materials.h"
#include "host.h"
#include "car_audio.h"
#include "car_grip.h"
#include "cliprec.h"
#include "decal_depth.h"
#include "gpuclients.h"
#include "headlights.h"
#include "live_picture.h"
#include "onscreen_keyboard.h"
#include "post_cuts.h"
#include "pre_treatment.h"
#include "rain_cover.h"
#include "realworld_materials.h"
#include "replay_input.h"
#include "roadfilm.h"
#include "roam_online.h"
#include "save_timing.h"
#include "server_loader.h"
#include "sign_diag.h"
#include "soft_smoke_half.h"
#include "stream_key.h"
#include "temporal_render.h"
#include "temporal_state.h"
#include "underglow_render.h"
#include "underglow_ui.h"
#include "x360audio.h"

/* alpha_to_coverage.c */
int alpha_to_coverage_draw(const uint32_t *rs, unsigned samples, int blended) { return (int){0}; }

/* auxlights.c */
int auxlights_enabled(void) { return (int){0}; }

/* fe_console.c */
void brightness_init(void) { }

/* car_audio.c */
int car_audio_code_region(uint32_t at) { return (int){0}; }

/* car_audio.c */
int car_audio_dispatch(Cpu *c,uint32_t target) { return (int){0}; }

/* car_grip_bridge.c */
void car_grip_init(void) { }

/* materials.m */
int carpaint_ab_shot(char *path, size_t n) { return (int){0}; }

/* clearcoat.c */
int clearcoat_enabled(void) { return (int){0}; }

/* clearcoat.c */
int clearcoat_shader_hash(uint64_t hash) { return (int){0}; }

/* cliprec.mm */
void cliprec_action(int unused) { }

/* cliprec.mm */
void cliprec_present(id<MTLCommandBuffer> __unsafe_unretained cb, id<MTLTexture> __unsafe_unretained src, id<CAMetalDrawable> __unsafe_unretained drawable, float headroom) { }

/* cliprec.mm */
void cliprec_status(char *buf, int size) { }

/* decal_depth.m */
int decal_depth_ground(uint32_t tex0) { return (int){0}; }

/* decal_depth.m */
void decal_depth_offset(float *bias, float *slope) { }

/* decal_depth.m */
int decal_depth_tagged(uint32_t tex0) { return (int){0}; }

/* detail.c */
int detail_ab_shot(char *path, size_t n) { return (int){0}; }

/* feedback.c */
void feedback_poll_pause(void) { }

/* feedback.c */
void feedback_suppress(unsigned reason, int on) { }

/* gpuclients.m */
void gpuclients_cached(GPUClientsSample *out) { }

/* headlights.m */
void headlights_bind(id<MTLRenderCommandEncoder> e, const HLConstants *k, int receiver) { }

/* headlights.m */
int headlights_casting(void) { return (int){0}; }

/* headlights.m */
id<MTLTexture> headlights_colour(void) { return (id<MTLTexture>){0}; }

/* headlights.m */
id<MTLTexture> headlights_depth(void) { return (id<MTLTexture>){0}; }

/* headlights.m */
int headlights_draw(const SmResult *vs, uint64_t pixel_hash, int main_target, HLConstants *out) { return (int){0}; }

/* headlights.m */
void headlights_drawn(int receiver) { }

/* headlights.m */
int headlights_enabled(void) { return (int){0}; }

/* headlights.m */
id<MTLRenderCommandEncoder> headlights_encoder(id<MTLCommandBuffer> command) { return (id<MTLRenderCommandEncoder>){0}; }

/* headlights.m */
int headlights_material(uint64_t pixel_hash) { return (int){0}; }

/* headlights.m */
void headlights_missed(void) { }

/* headlights.m */
char *headlights_shader(const char *source, const SmResult *reflection, int caster, int material) { return (char *){0}; }

/* lighting.c */
float lighting_inv_shadow_strength(float original) { return (float){0}; }

/* live_fake.m */
void live_fake_go(void) { }

/* live_picture.c */
void live_picture_on_reset(Cpu *c) { }

/* live_picture_sweep.c */
void live_picture_sweep_step(const char *phase) { }

/* materials.m */
int mat_aux_ab_held(void) { return (int){0}; }

/* materials.m */
int mat_aux_constants(const SmResult *vs, const float (*vsc)[4], float out[52][4]) { return (int){0}; }

/* materials.m */
MatAuxDraw mat_aux_draw;

/* materials.m */
void mat_aux_emit(void) { }

/* materials.m */
void mat_aux_fallback(int reason) { }

/* materials.m */
void mat_aux_frame(void) { }

/* materials.m */
char *mat_aux_shader(const SmResult *pc, int stage, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* materials.m */
void mat_bone_car_cube(uint32_t tex) { }

/* materials.m */
int mat_bone_constants(const float (*vsc)[4], float out[MAT_BONE_K][4]) { return (int){0}; }

/* materials.m */
int mat_bone_draw(uint32_t tex[3], int *skip) { return (int){0}; }

/* materials.m */
void mat_bone_emit(void) { }

/* materials.m */
void mat_bone_failure(int pipeline) { }

/* materials.m */
void mat_bone_frame(void) { }

/* materials.m */
void mat_bone_reset(void) { }

/* materials.m */
char *mat_bone_shader(const uint32_t *tokens, uint32_t n, const SmResult *pc, int stage, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* materials.m */
void mat_bone_skip(int reason) { }

/* materials.m */
int mat_carbon_lamp_draw(void) { return (int){0}; }

/* materials.m */
char *mat_carbon_lamp_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
void mat_cardraw_missing(int kind, int sampler, uint32_t guest, uint32_t fmt) { }

/* materials.m */
void mat_cardraw_note(const uint32_t *rs) { }

/* materials.m */
uint32_t mat_carnm_texture(void) { return (uint32_t){0}; }

/* materials.m */
char *mat_clearcoat_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
int mat_extra_texture(int id) { return (int){0}; }

/* materials.m */
int mat_flake_volume_ok(void) { return (int){0}; }

/* materials.m */
int mat_glass_constants(const SmResult *pcvs, const SmResult *pcps, const float (*vsc)[4], const float (*psc)[4], float out[32][4]) { return (int){0}; }

/* materials.m */
MatGlassDraw mat_glass_draw;

/* materials.m */
void mat_glass_emit(int blended) { }

/* materials.m */
int mat_glass_enabled(void) { return (int){0}; }

/* materials.m */
void mat_glass_failure(int pipeline) { }

/* materials.m */
void mat_glass_frame(void) { }

/* materials.m */
char *mat_glass_shader(const uint32_t *tokens, uint32_t n, const SmResult *pc, int stage, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* materials.m */
int mat_glass_uv1(const uint8_t *bytes, uint32_t size, const float **out, uint32_t *matched) { return (int){0}; }

/* materials.m */
void mat_glass_uv_note(int found, uint32_t vertices, uint32_t matched) { }

/* materials.m */
int mat_grass_constants(const SmResult *pcvs, const SmResult *pcps, const float (*vsc)[4], const float (*psc)[4], float out[64][4]) { return (int){0}; }

/* materials.m */
void mat_grass_diag_emit(int n, const float k[64][4]) { }

/* materials.m */
void mat_grass_diag_frame(void) { }

/* materials.m */
MatGrassDraw mat_grass_draw;

/* materials.m */
int mat_grass_enabled(void) { return (int){0}; }

/* materials.m */
const uint8_t *mat_grass_noise(uint32_t *w, uint32_t *h) { return (const uint8_t *){0}; }

/* materials.m */
char *mat_grass_shader(const SmResult *pc, int stage, int shell, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* materials.m */
int mat_grass_shadow_slot(const SmResult *pc) { return (int){0}; }

/* materials.m */
uint32_t mat_grass_texture(int slot) { return (uint32_t){0}; }

/* materials.m */
const uint8_t *mat_grass_volume(uint32_t *size) { return (const uint8_t *){0}; }

/* materials.m */
int mat_headlamp_clear_draw(void) { return (int){0}; }

/* materials.m */
char *mat_headlamp_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
int mat_is_particle(int id) { return (int){0}; }

/* materials.m */
char *mat_realworld_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id, int chrome) { return (char *){0}; }

/* materials.m */
char *mat_replace(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
const uint8_t *mat_ripple_frame(int i, uint32_t *w, uint32_t *h) { return (const uint8_t *){0}; }

/* materials.m */
char *mat_roadfilm_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
int mat_soft_particle_view(void) { return (int){0}; }

/* materials.m */
char *mat_soft_smoke_late_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
char *mat_soft_smoke_resolved_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
char *mat_soft_smoke_shader(const uint32_t *tokens, uint32_t n, const SmResult *refl, int *id) { return (char *){0}; }

/* materials.m */
int mat_trees_constants(const SmResult *pcvs, const float (*vsc)[4], float out[32][4]) { return (int){0}; }

/* materials.m */
MatTreesDraw mat_trees_draw;

/* materials.m */
void mat_trees_emit(int blended) { }

/* materials.m */
int mat_trees_enabled(void) { return (int){0}; }

/* materials.m */
void mat_trees_failure(int pipeline) { }

/* materials.m */
void mat_trees_frame(void) { }

/* materials.m */
char *mat_trees_shader(const uint32_t *tokens, uint32_t n, const SmResult *pc, int stage, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* materials.m */
void mat_water_emit(int variant) { }

/* materials.m */
void mat_water_failure(int pipeline) { }

/* materials.m */
char *mat_water_shader(const SmResult *pc, int stage, uint16_t input_int, uint16_t input_uint) { return (char *){0}; }

/* onscreen_keyboard.c */
int osk_pad(int port, uint32_t buttons, int up, int down, int left, int right,
            float lx, float ly, int connected, int xbox) { return (int){0}; }

/* onscreen_keyboard.c */
int osk_visible(void) { return (int){0}; }

/* padbind.c */
void padbind_sync(Cpu *c) { }

/* padbind.c */
void padbind_test_player_triggers(void) { }

/* padbind.c */
void padbind_trigger_sample(unsigned step, float lt, float rt, uint32_t z, uint32_t rz, int native) { }

/* padfx.m */
void padfx_close(void) { }

/* padfx.m */
void padfx_connect(void *gc) { }

/* padfx.m */
void padfx_disconnect(void *gc) { }

/* padfx.m */
void padfx_player_update(int slot, void *gc) { }

/* padfx.m */
void padfx_stop(void) { }

/* padfx.m */
void padfx_update(void *gc, int dualsense, float lt, float rt) { }

/* padlink.c */
void padlink_battery(void *id, float level, int state) { }

/* padlink.c */
void padlink_detach(void *id) { }

/* padlink.c */
void padlink_select(void *id, const char *what) { }

/* particles_physical.c */
int particles_physical_enabled(void) { return (int){0}; }

/* portmenu.m */
int portmenu_char(uint32_t ch) { return (int){0}; }

/* portmenu.m */
int portmenu_command_key(uint8_t vk, int repeat) { return (int){0}; }

/* portmenu.m */
int portmenu_is_open(void) { return (int){0}; }

/* portmenu.m */
int portmenu_key(uint8_t vk, int down, int repeat) { return (int){0}; }

/* portmenu.m */
int portmenu_mouse(int kind, double vx, double vy, double dy) { return (int){0}; }

/* portmenu.m */
uint32_t portmenu_pad(uint32_t phys, int up, int down, int left, int right, float lx, float ly, int home, int touchpad, int has_touchpad,
                      uint32_t *inject) { return (uint32_t){0}; }

/* portmenu.m */
void portmenu_status(const char *fmt, ...) { }

/* portmenu.m */
void portmenu_update(void) { }

/* post_cuts.c: retain coverage attachments in the native post chain. */
unsigned post_cuts_ao(int proof, int ordinary_depth, int reuse, int empty) { return 0; }

/* post_cuts.c */
int post_cuts_curve(uint32_t w, uint32_t h, int split) { return (int){0}; }

/* post_cuts.c */
const char *post_cuts_curve_source(void) { return (const char *){0}; }

/* post_cuts.c */
int post_cuts_enabled(void) { return (int){0}; }

/* post_cuts.c */
int post_cuts_full_target(int split, unsigned level, unsigned slice,
                          uint32_t w, uint32_t h, uint32_t ow, uint32_t oh) { return (int){0}; }

/* post_cuts.c */
int post_cuts_quad(uint32_t x, uint32_t y, uint32_t z, uint32_t w, uint32_t h,
                   uint32_t depth, uint32_t ow, uint32_t oh) { return (int){0}; }

/* x360_post.m */
int postfx_ab_shot(char *path, size_t n) { return (int){0}; }

/* x360_post.m */
int postfx_look_variant(const char *v) { return (int){0}; }

/* pre_treatment.m */
int pre_treatment_register(PreTreatmentGraph *graph,const PreTreatmentNode *node) { return (int){0}; }

/* probe.m */
void probe_applied(int bit, int n) { }

/* probe.m */
void probe_present(id<MTLCommandBuffer> cmd, id<MTLTexture> tex) { }

/* probe.m */
int probe_sig;

/* probe.m */
void probe_tint(uint32_t fmt, uint8_t *p, size_t size, int bgra32) { }

/* padprompts.c */
void prompts_input(int pad) { }

/* padprompts.c */
void prompts_mouse_moved(float points) { }

/* padprompts.c */
void prompts_pad_seen(int connected) { }

/* padprompts.c */
void prompts_pointer_visible(void) { }

/* pub_update_launch.m */
void pub_update_launch(int *argc, char ***argv, const char *profilePath) { }

/* rain_cover.m */
void rain_cover_bind(id<MTLRenderCommandEncoder> encoder, const SmResult *vs) { }

/* rain_cover.m */
int rain_cover_enabled = -1;

/* rain_cover.m */
int rain_cover_on(void) { return (int){0}; }

/* rain_cover.m */
int rain_cover_ripple(uint64_t hash) { return (int){0}; }

/* rain_cover.m */
char *rain_cover_shader(const uint32_t *tokens, uint32_t n, const SmResult *r, int *id, int film) { return (char *){0}; }

/* realworld_materials.c */
int realworld_materials_draw(uint64_t ps, uint64_t vs) { return (int){0}; }

/* realworld_materials.c */
int realworld_materials_mode(void) { return (int){0}; }

/* realworld_materials.c */
float *realworld_materials_panes(const void *vertices, uint32_t nv, uint32_t stride, uint32_t position,
                               uint32_t normal, const void *indices, uint32_t ni, uint32_t isz, uint32_t first, int mask) { return (float *){0}; }

/* realworld_materials.c */
uint32_t realworld_materials_rim_mask(void) { return (uint32_t){0}; }

/* realworld_materials.c */
void realworld_materials_set_hold(void (*add)(uint32_t), void (*release)(uint32_t)) { }

/* realworld_materials.c */
int realworld_materials_window_mask(void) { return (int){0}; }

/* cliprec.mm */
void replay_arm_action(int unused) { }

/* portmenu.m */
void replay_controls_cancel(void) { }

/* portmenu.m */
void replay_controls_disconnect(void) { }

/* cliprec.mm */
void replay_save_action(int unused) { }

/* report.m */
void report_init(void) { }

/* report.m */
void report_note(const char *fmt, ...) { }

/* report.m */
int report_shot(char *path, size_t n) { return (int){0}; }

/* report.m */
void report_shot_ready(const char *path) { }

/* roadfilm.m */
int roadfilm_draw(uint64_t hash, float wetness) { return (int){0}; }

/* roadfilm.m */
int roadfilm_enabled(void) { return (int){0}; }

/* roadfilm.m */
int roadfilm_shader_hash(uint64_t hash) { return (int){0}; }

/* roam_game.c */
atomic_int roam_online_active;

/* rumble.m */
void rumble_close(void) { }

/* rumble.m */
void rumble_update(void) { }

/* save_timing.c */
unsigned save_timing_enter(const char *stage) { return (unsigned int){0}; }

/* save_timing.c */
void save_timing_leave(unsigned span, int64_t result) { }

/* server_loader.c */
int server_dispatch(Cpu *c, uint32_t t) { return (int){0}; }

/* server_loader.c */
int server_free(Cpu *c, uint32_t h) { return (int){0}; }

/* server_loader.c */
uint32_t server_handle(void) { return (uint32_t){0}; }

/* server_loader.c */
const char *server_import(uint32_t s, unsigned *i) { return (const char *){0}; }

/* server_loader.c */
int server_library_name(const char *name) { return (int){0}; }

/* server_loader.c */
uint32_t server_load(Cpu *c, const char *path) { return (uint32_t){0}; }

/* server_loader.c */
uint32_t server_proc(uint32_t h, uint32_t n) { return (uint32_t){0}; }

/* settings_port.c */
const char *settings_game_language(void) { return (const char *){0}; }

/* sign_diag.m */
int sign_diag_active(void) { return (int){0}; }

/* sign_diag.m */
int sign_diag_canonical(unsigned stage) { return (int){0}; }

/* sign_diag.m */
id<MTLFunction> sign_diag_direct(uint64_t key,const char *source) { return (id<MTLFunction>){0}; }

/* sign_diag.m */
void sign_diag_draw(uint64_t vs,uint64_t ps,unsigned type,unsigned prims,int indexed,int32_t base,unsigned start,const SmResult *vsinfo,const SmResult *psinfo) { }

/* sign_diag.m */
void sign_diag_finish_present(id<MTLCommandBuffer> cb) { }

/* sign_diag.m */
void sign_diag_freeze(const char *name,void *bytes,size_t size) { }

/* sign_diag.m */
int sign_diag_on;

/* sign_diag.m */
void sign_diag_pipeline(uint64_t key,MTLRenderPipelineDescriptor *descriptor,const char *source) { }

/* sign_diag.m */
void sign_diag_present(id<MTLCommandBuffer> cb,id<MTLTexture> final) { }

/* sign_diag.m */
void sign_diag_record_history(const char *name,const void *bytes,size_t size) { }

/* sign_diag.m */
void sign_diag_replay(id<MTLRenderCommandEncoder> proxy) { }

/* sign_diag.m */
void sign_diag_scene(id<MTLCommandBuffer> cb,id<MTLTexture> scene) { }

/* sign_diag.m */
id<MTLRenderCommandEncoder> sign_diag_tee(id<MTLRenderCommandEncoder> encoder,uint64_t key,
    id<MTLTexture> color,id<MTLTexture> depth,id<MTLDepthStencilState> readonly_depth) { return (id<MTLRenderCommandEncoder>){0}; }

/* sign_diag.m */
id<MTLTexture> sign_diag_texture_view(uint32_t guest,id<MTLTexture> full) { return (id<MTLTexture>){0}; }

/* slowlog.m */
void slowlog_lum_wait(uint64_t ns) { }

/* soft_smoke_half.m */
const char soft_half_up_msl[] =
"inline float half_rel(float a, float b) { return abs(a-b)/max(1.0f-b,1e-7f); }\n"
"inline float4 half_up(texture2d<float> c, depth2d<float> lz, depth2d<float> fz, float2 px, uint plain) {\n"
"    float z=fz.read(uint2(px));\n"
"    float2 l=px*float2(c.get_width(),c.get_height())/float2(fz.get_width(),fz.get_height())-0.5f, f=fract(l);\n"
"    int2 b=int2(floor(l)), m=int2(c.get_width()-1,c.get_height()-1);\n"
"    float4 s[4]; float worst=0.0f, near=1e30f; int best=0;\n"
"    for (int j=0;j<4;++j) {\n"
"        uint2 q=uint2(clamp(b+int2(j&1,j>>1),int2(0),m)); s[j]=c.read(q);\n"
"        float e=half_rel(lz.read(q),z); worst=max(worst,e); if (e<near) { near=e; best=j; }\n"
"    }\n"
"    if (plain || worst<=0.1f) return mix(mix(s[0],s[1],f.x),mix(s[2],s[3],f.x),f.y);\n"
"    return s[best];\n"
"}\n";

/* soft_smoke_half.m */
void soft_smoke_half_ab(NSArray *draws, id<MTLTexture> layer, int half) { }

/* soft_smoke_half.m */
int soft_smoke_half_ab_on(void) { return (int){0}; }

/* soft_smoke_half.m */
void soft_smoke_half_warm(void) { }

/* splitcapture.c */
void split_capture_receiver_texture(unsigned stage, uint32_t texture) { }

/* stream_key.m */
void stream_key_forget(int unused) { }

/* stream_key.m */
int stream_key_route_event(NSEvent *event) { return (int){0}; }

/* temporal_render.m */
TemporalMotionTarget *temporal_draw_target;

/* temporal_render.m */
TemporalViewId temporal_draw_view=TEMPORAL_VIEW_COUNT;

/* temporal_state.c */
int temporal_pose_commit(TemporalViewId id, uint64_t serial) { return (int){0}; }

/* temporal_state.c */
const TemporalPartPose *temporal_pose_draw(TemporalViewId id) { return (const TemporalPartPose *){0}; }

/* temporal_render.m */
int temporal_render_constants(const TemporalViewState *view,const TemporalPartPose *pose,int supported,const float raster[2],SmTemporalAux *out) { return (int){0}; }

/* temporal_render.m */
int temporal_render_moved(const TemporalViewState *view,const TemporalPartPose *pose,const uint32_t viewport[4]) { return (int){0}; }

/* temporal_render.m */
int temporal_render_pipeline(id<MTLDevice> device,MTLRenderPipelineDescriptor *p,NSString *vertex,NSString *fragment,int samples) { return (int){0}; }

/* temporal_render.m */
id<MTLRenderCommandEncoder> temporal_render_record(id<MTLRenderCommandEncoder> real,TemporalMotionTarget *target,TemporalViewId view,id<MTLRenderPipelineState> pso,const SmTemporalAux *aux) { return (id<MTLRenderCommandEncoder>){0}; }

/* temporal_render.m */
id<MTLTexture> temporal_render_resolve(id<MTLDevice> device,id<MTLCommandBuffer> cb,TemporalMotionTarget *t,id<MTLTexture> z,TemporalViewId view){ return (id<MTLTexture>){0}; }

/* temporal_render.m */
int temporal_render_scene(id<MTLTexture> colour,id<MTLTexture> depth,uint64_t serial,const uint32_t viewport[4],int eligible) { return (int){0}; }

/* temporal_state.c */
int temporal_state_requested;

/* temporal_state.c */
const TemporalViewState *temporal_view_state(TemporalViewId id) { return (const TemporalViewState *){0}; }

/* traffic_detail.c */
int traffic_detail_ab_shot(char *path, size_t size) { return (int){0}; }

/* underglow_render.m */
void underglow_render_mesh_observe(const UGMeshView *m) { }

/* underglow_render.m */
int underglow_render_observing(void) { return (int){0}; }

/* underglow_ui.c */
int underglow_ui_step(const char *step, uint64_t elapsed, const char *pkg, const char **key) { return (int){0}; }

/* widescreen.c */
void widescreen_drop_offset(Cpu *c, uint32_t vec) { }

/* widescreen.c */
void widescreen_drop_quad(Cpu *c, uint32_t verts, uint32_t stride) { }

/* widescreen.c */
void widescreen_mode(int i, uint32_t *w, uint32_t *h) { }

/* widescreen.c */
void widescreen_projection(Cpu *c, uint32_t proj) { }

/* x360_textures.m */
uint32_t x360_arrest_draws;

/* x360_textures.m */
int x360_hd_creating;

/* x360_post.m */
int x360_post_ssao_enabled(void) { return (int){0}; }

/* x360.m */
void x360_reflection_size(uint32_t *w, uint32_t *h) { }

/* x360.m */
int x360_reflection_target(uint32_t guest, uint32_t w, uint32_t h) { return (int){0}; }

/* x360.m */
int x360_shadow_border(void) { return (int){0}; }

/* x360.m */
void x360_shadow_camera(Cpu *c, uint32_t view, uint32_t proj) { }

/* x360.m */
int x360_shadow_edge(void) { return (int){0}; }

/* x360.m */
void x360_shadow_texture_size(uint32_t *w, uint32_t *h) { }

/* x360_textures.m */
uint32_t x360_ui_diag_hash(uint32_t guest) { return (uint32_t){0}; }

/* x360audio.c */
size_t x360music_read(X360MusicHandle *h, void *dst, size_t n) { return (size_t){0}; }

/* x360audio.c */
int64_t x360music_seek(X360MusicHandle *h, int64_t distance, unsigned method) { return (int64_t){0}; }
