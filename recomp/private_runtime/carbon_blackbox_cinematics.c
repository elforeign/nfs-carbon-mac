/* Native movie request and witnessed INIS observations on the guest thread.
 * Layout witnesses: MoviePlayer 00595210/0057F3B0; INIS 0076D6F0,
 * 00763300; track getters 0045D740/0045D750. Other INIS classes are not decoded yet. */
#include "host.h"
#include "blackbox.h"
#include <math.h>
#include <string.h>

static int cin_ok(uint32_t address) {
    return address >= 0x1000u && address < 0xFFFFF000u;
}
static uint32_t cin_hash(uint32_t address) {
    uint32_t hash = UINT32_MAX;
    for (unsigned i = 0; i < 64; ++i) {
        unsigned ch = M8(address + i);
        if (!ch) return i ? hash : 0;
        if (ch < 0x20 || ch >= 0x7F) return 0;
        hash = hash * 33 + ch;
    }
    return 0;
}
static int cin_movie(BlackboxCarbonCinematic *s) {
    if (!cin_ok(s->address)) return s->address == 0;
    s->class_id = M32(s->address);
    s->state = M32(s->address + 0x120);
    s->next = M32(s->address + 0x124);
    s->decoded = 1;
    return 1;
}

static BlackboxCarbonCinematic cin_last_movie, cin_last_nis;
static uint32_t cin_request_player, cin_request_hash;

/* Capture short requests even if the player disappears before the next frame.
 * Observe before the provider/native call; never change its CPU or guest state. */
void carbon_blackbox_movie_request(uint32_t player) {
    if (!blackbox_enabled() || !G) return;
    BlackboxCarbonCinematic s = {.address = player};
    int valid = cin_movie(&s);
    if (player && valid) s.filename_hash = cin_hash(player + 0x1C);
    cin_request_player = player;
    cin_request_hash = s.filename_hash;
    blackbox_record_carbon_cinematic(BB_CARBON_MOVIE, BB_CIN_PLAY, &s, valid, 0, blackbox_now_ns());
}

void carbon_blackbox_cinematics(uint64_t frame, uint64_t now) {
    if (!blackbox_enabled() || !G) return;
    static int have, last_movie_valid, last_nis_valid;
    static uint64_t clock_sample;
    BlackboxCarbonCinematic movie = {.address = M32(0x00A97BB4u)};
    int movie_valid = cin_movie(&movie);
    if (movie.address && movie_valid) {
        if (movie.address == cin_request_player) movie.filename_hash = cin_request_hash;
        else if (movie.address == cin_last_movie.address) movie.filename_hash = cin_last_movie.filename_hash;
        else movie.filename_hash = cin_hash(movie.address + 0x1C);
    } else cin_request_player = cin_request_hash = 0;
    BlackboxCarbonCinematic nis = {.address = M32(0x00B4D964u)};
    int nis_valid = nis.address == 0 || cin_ok(nis.address);
    if (cin_ok(nis.address)) {
        nis.class_id = M32(nis.address);
        if (nis.class_id == 0x009EC6E8u) {
            nis.decoded = 1;
            nis.state = M32(nis.address + 0x2E0);
            nis.track = M32(nis.address + 0x390);
            int identity = have && nis.address == cin_last_nis.address &&
                nis.class_id == cin_last_nis.class_id && nis.state == cin_last_nis.state &&
                nis.track == cin_last_nis.track;
            if (!identity || now - clock_sample >= 250000000ull) {
                clock_sample = now;
                if (cin_ok(nis.track) && M32(nis.track) == 0x009C5FE0u) {
                    nis.elapsed = M32(nis.track + 0x20);
                    nis.length = M32(nis.track + 0x28);
                    float elapsed, length;
                    memcpy(&elapsed, &nis.elapsed, sizeof elapsed);
                    memcpy(&length, &nis.length, sizeof length);
                    nis.clock_valid = isfinite(elapsed) && isfinite(length) && elapsed >= 0 && length > 0;
                }
                nis.clock_since = identity && nis.clock_valid && cin_last_nis.clock_valid &&
                    nis.elapsed == cin_last_nis.elapsed && nis.length == cin_last_nis.length ?
                    cin_last_nis.clock_since : now;
            } else {
                nis.elapsed = cin_last_nis.elapsed; nis.length = cin_last_nis.length;
                nis.clock_valid = cin_last_nis.clock_valid;
                nis.clock_since = cin_last_nis.clock_since;
            }
        }
    }
    if (!have || movie_valid != last_movie_valid || memcmp(&movie, &cin_last_movie, sizeof movie))
        blackbox_record_carbon_cinematic(BB_CARBON_MOVIE, BB_CIN_STATE, &movie, movie_valid, frame, now);
    if (!have || nis_valid != last_nis_valid || memcmp(&nis, &cin_last_nis, sizeof nis))
        blackbox_record_carbon_cinematic(BB_CARBON_NIS, BB_CIN_STATE, &nis, nis_valid, frame, now);
    cin_last_movie = movie; cin_last_nis = nis;
    last_movie_valid = movie_valid; last_nis_valid = nis_valid; have = 1;
}
