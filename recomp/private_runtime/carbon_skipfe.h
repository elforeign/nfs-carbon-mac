/* Retail developer globals, applied after PE sections and before its entry point.
 * PRIVATE_CARBON_SKIPFE binds these addresses to the decoded executable hash. */
#include <errno.h>
#include <math.h>

/* The first normal local player is in A9FF5C/A9FF64 (0076FC60..0076FCA5).
 * 0076E810 -> 0076E740 reads its Simable at interface-8. 006D7EA0 reads
 * Simable+0x4c and tail-calls RigidBody GetPosition, 006C6FF0: **(+0x30)+0x10.
 * Check those concrete methods and read the physics state without guest calls. */
int private_carbon_player_pose(float *position, float *forward) {
    if (!PRIVATE_CARBON_SKIPFE) return 0;
    uint32_t count = M32(0x00A9FF64), list = M32(0x00A9FF5C);
    if (!count || count > 2 || !list) return 0;
    uint32_t player = M32(list), vt = player ? M32(player) : 0;
    if (player < 8 || !vt || M32(vt + 4) != 0x0076E810) return 0;
    uint32_t sim = M32(player - 8), sv = sim ? M32(sim) : 0;
    if (!sv || M32(sv + 0x60) != 0x006D7EA0) return 0;
    uint32_t body = M32(sim + 0x4c), bv = body ? M32(body) : 0;
    if (!bv) return 0;
    if (M32(bv + 0x20) != 0x006C6FF0) {
        static int reported;
        if (!reported++) fprintf(stderr, "PRIVATE CARBON POSITION unsupported body=%08x vtable=%08x get_position=%08x\n", body,bv,M32(bv+0x20));
        return 0;
    }
    uint32_t holder = M32(body + 0x30), state = holder ? M32(holder) : 0;
    if (!state) return 0;
    float physics[3];
    memcpy(physics, G + state + 0x10, sizeof physics);
    if (!isfinite(physics[0]) || !isfinite(physics[1]) || !isfinite(physics[2])) return 0;
    static int reported;
    if (!reported++) fprintf(stderr, "PRIVATE CARBON POSITION source=rigidbody player=%08x sim=%08x body=%08x state=%08x reader=006c6ff0\n",player,sim,body,state);
    position[0] = physics[2]; position[1] = -physics[0]; position[2] = physics[1];
    if (forward) {
        /* 006C70E0 reads the forward row from this same physics state. */
        memcpy(physics, G + state + 0x90, sizeof physics);
        forward[0] = physics[2]; forward[1] = -physics[0]; forward[2] = physics[1];
    }
    return 1;
}

int private_carbon_player_position(float *position) {
    return private_carbon_player_pose(position, NULL);
}

static void private_carbon_skipfe_setup(void) {
    const char *enabled = getenv("NFS_CARBON_SKIPFE");
    const char *track = getenv("NFS_CARBON_SKIPFE_TRACK");
    const char *car = getenv("NFS_CARBON_SKIPFE_CAR");
    const char *event = getenv("NFS_CARBON_SKIPFE_EVENT");
    const char *start = getenv("NFS_CARBON_SKIPFE_START");
    const char *traffic = getenv("NFS_CARBON_SKIPFE_TRAFFIC");
    int request = enabled && *enabled && strcmp(enabled, "0");
    int has_track = track && *track, has_car = car && *car;
    int has_start = start && *start;
    int has_traffic = traffic && *traffic;
    int has_event = event && *event;
    if (!request && !has_track && !has_car && !has_start && !has_traffic && !has_event) return;
    if (!PRIVATE_CARBON_SKIPFE) {
        fprintf(stderr, "NFS_CARBON_SKIPFE: unsupported private image\n");
        exit(2);
    }
    if (request && strcmp(enabled, "1")) {
        fprintf(stderr, "NFS_CARBON_SKIPFE: expected 0 or 1\n");
        exit(2);
    }
    uint32_t number = 0;
    if (has_track) {
        /* Decimal only, with overflow rejected before multiplication. */
        for (const unsigned char *p = (const unsigned char *)track; *p; ++p) {
            if (*p < '0' || *p > '9' || number > (UINT32_MAX - (*p - '0')) / 10) {
                fprintf(stderr, "NFS_CARBON_SKIPFE_TRACK: expected a positive uint32 decimal\n");
                exit(2);
            }
            number = number * 10 + (*p - '0');
        }
        if (!number) {
            fprintf(stderr, "NFS_CARBON_SKIPFE_TRACK: expected a positive uint32 decimal\n");
            exit(2);
        }
    }
    if (has_car) {
        size_t length = strlen(car);
        if (length > 63 || strspn(car, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_") != length) {
            fprintf(stderr, "NFS_CARBON_SKIPFE_CAR: expected a car name of 1..63 letters, digits or underscores\n");
            exit(2);
        }
    }
    char event_id[64];
    uint32_t event_mode = 0, opponents = 0;
    if (has_event) {
        const char *colon = strchr(event, ':');
        size_t n = colon ? (size_t)(colon - event) : 0;
        if (!n || n >= sizeof event_id ||
            strspn(event, "abcdefghijklmnopqrstuvwxyz0123456789._") != n) goto bad_event;
        memcpy(event_id, event, n); event_id[n] = 0;
        const char *p = colon + 1;
        uint32_t *values[] = {&event_mode, &opponents};
        for (unsigned i = 0; i < 2; ++i) {
            if (*p < '0' || *p > '9') goto bad_event;
            while (*p >= '0' && *p <= '9') {
                if (*values[i] > (UINT32_MAX - (*p - '0')) / 10) goto bad_event;
                *values[i] = *values[i] * 10 + (*p++ - '0');
            }
            if (*p != (i == 0 ? ':' : '\0')) goto bad_event;
            if (i == 0) ++p;
        }
        if (event_mode > 3 || opponents < 1 || opponents > 7) goto bad_event;
    }
    float density = 0;
    if (has_traffic) {
        char *end;
        errno = 0;
        density = strtof(traffic, &end);
        if (!strchr("+-.0123456789", *traffic) || errno || end == traffic || *end ||
            !isfinite(density) || density < 0 || density > 100) {
            fprintf(stderr, "NFS_CARBON_SKIPFE_TRAFFIC: expected a finite percentage 0..100\n");
            exit(2);
        }
    }
    float position[3];
    if (has_start) {
        const char *p = start;
        for (unsigned k = 0; k < 3; ++k) {
            char *end;
            errno = 0;
            if (!*p || !strchr("+-.0123456789", *p)) goto bad_start;
            position[k] = strtof(p, &end);
            if (errno || end == p || !isfinite(position[k]) || (*end != (k < 2 ? ',' : '\0'))) goto bad_start;
            p = end + (k < 2);
        }
        if (position[0] == 0 && position[1] == 0 && position[2] == 0) goto bad_start;
    }
    if (has_track) M32(0x00A6313C) = number;                 /* SkipFETrackNumber */
    if (has_car) {
        uint32_t name = galloc((uint32_t)strlen(car) + 1);
        memcpy(G + name, car, strlen(car) + 1);
        M32(0x00A63144) = name;                             /* SkipFEPlayerCar */
    }
    if (has_event) {
        uint32_t name = galloc((uint32_t)strlen(event_id) + 1);
        memcpy(G + name, event_id, strlen(event_id) + 1);
        M32(0x00A63140) = name;                             /* SkipFERaceID */
        M32(0x00A9E630) = opponents;
        M32(0x00A9E648) = event_mode;
        fprintf(stderr, "PRIVATE CARBON EVENT id=%s mode=%u opponents=%u reverse=%u\n",
                event_id, event_mode, opponents, M32(0x00A9E634));
    }
    /* 007A97B0 reads render XYZ and produces physics (-Y,Z,X). */
    if (has_start) memcpy(G + 0x00A9E6E0, position, sizeof position);
    M32(0x00A9E620) = 1;                                   /* SkipFE */
    if (has_traffic) memcpy(G + 0x00A9E640, &density, sizeof density); /* SkipFETrafficDensity */
    M32(0x00A9E6D8) = 1;                                   /* SkipMovies */
    fprintf(stderr, "PRIVATE CARBON SKIPFE enabled track=%u car=%s movies=1\n",
            M32(0x00A6313C), (const char *)G + M32(0x00A63144));
    if (has_start) fprintf(stderr, "PRIVATE CARBON START render=%.6f,%.6f,%.6f physics=%.6f,%.6f,%.6f\n",
                           position[0], position[1], position[2], -position[1], position[2], position[0]);
    return;
bad_event:
    fprintf(stderr, "NFS_CARBON_SKIPFE_EVENT: expected id:mode:opponents (id 1..63 lowercase letters, digits, . or _; mode 0..3; opponents 1..7)\n");
    exit(2);
bad_start:
    fprintf(stderr, "NFS_CARBON_SKIPFE_START: expected three finite, nonzero render coordinates x,y,z\n");
    exit(2);
}
