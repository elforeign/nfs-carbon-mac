/* Synthetic pool/CRT seam over the production extent allocator. No game data. */
#include "host.h"
#include "heap.h"
#include <stdarg.h>
#include <stdlib.h>
#include <sys/mman.h>

uint8_t *G;
int diag_on, boot_trace;
const char *game_dir = ".";
__thread uint32_t last_error;
static Heap *resource, *process;
static unsigned checks, resource_calls;
#define CHECK(v, why) do { ++checks; if (!(v)) { fprintf(stderr, "FAIL %s (%u)\n", why, checks); exit(1); } } while (0)
void *heap_test_memset(void *p, int c, size_t n) { return memset(p, c, n); }
uint32_t gmalloc(uint32_t n) {
    ++resource_calls;
    uint32_t p = heap_alloc(resource, n ? n : 1);
    CHECK(p, "oversized Y00 entered fragmented resource heap");
    return p;
}
void gfree(uint32_t p) { if (p) CHECK(heap_free(resource, p), "free sent process backing to resource heap"); }
uint32_t gmalloc_size(uint32_t p) { return heap_size(resource, p); }
uint32_t galloc(uint32_t n) { return gmalloc(n); }
uint32_t gstr(const char *s) { uint32_t p = gmalloc(strlen(s) + 1); strcpy((char *)G + p, s); return p; }
int win32_heap(Cpu *c, const char *fn) {
    if (!strcmp(fn, "GetProcessHeap")) RET(0x10000, 0);
    CHECK(arg(c, 0) == 0x10000 && arg(c, 1) == 0, "process heap arguments");
    if (!strcmp(fn, "HeapAlloc")) RET(heap_alloc(process, arg(c, 2)), 3);
    CHECK(!strcmp(fn, "HeapReAlloc"), "process heap operation");
    RET(heap_realloc(process, arg(c, 2), arg(c, 3), 0), 4);
}
void diag_event(const char *fmt, ...) { (void)fmt; }
void diag_begin_exit(void) { }
void app_restart_game_exited(int successful) { (void)successful; }
uint32_t host_fn(HostFn fn, const char *name) { (void)fn; (void)name; return 1; }
uint32_t call_guest(Cpu *c, uint32_t fn, int n, const uint32_t *a) { (void)c; (void)fn; (void)n; (void)a; abort(); }
int private_resolve(const char *s, char *out, size_t n) { snprintf(out, n, "%s", s); return 0; }
int private_win32(Cpu *c, const char *fn) { (void)c; (void)fn; return 0; }
int win32_threads(Cpu *c, const char *fn) { (void)c; (void)fn; return 0; }
uint32_t private_thread_create(uint32_t a, uint32_t b, uint32_t d, uint32_t e, uint32_t *f) { (void)a; (void)b; (void)d; (void)e; (void)f; return 0; }
int private_crt(Cpu *, const char *);
void carbon_y00_allocate(Cpu *, void (*)(Cpu *));

static uint32_t crt(Cpu *c, const char *name, uint32_t ret, uint32_t value) {
    Cpu call = *c;
    call.esp -= 256;
    uint32_t sp = call.esp;
    M32(sp) = ret; M32(sp + 4) = value;
    CHECK(private_crt(&call, name), "CRT dispatch");
    CHECK(call.esp == sp + 4, "cdecl stack cleanup");
    return call.eax;
}
static void pool(Cpu *c) {
    /* The decoded pool requests a 16-byte list node, then the raw backing.
     * Keep the two return sites distinct, as in 00476560. */
    uint32_t node = crt(c, "malloc", 0x00476677, 16);
    uint32_t size = ((arg(c, 0) + 23u) & ~3u) + 144u;
    uint32_t p = crt(c, "malloc", 0x0047668A, size);
    crt(c, "free", 0x00476542, node);
    c->eax = p;
    c->esp += 4;
}
static uint32_t request(Cpu *c, uint32_t size, uint32_t flags, uint32_t ret) {
    *c = (Cpu){0}; c->esp = 0x8000; c->ebx = 11; c->esi = 22; c->edi = 33; c->ebp = 44;
    M32(c->esp) = ret; M32(c->esp + 4) = size; M32(c->esp + 8) = flags;
    carbon_y00_allocate(c, pool);
    CHECK(c->esp == 0x8004 && c->ebx == 11 && c->esi == 22 && c->edi == 33 && c->ebp == 44, "wrapper preserves native ABI");
    return c->eax;
}
static void release(Cpu *c, uint32_t p) { crt(c, "free", 0x00476542, p); }

int main(void) {
    G = mmap(NULL, 0x80000000ull, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    CHECK(G != MAP_FAILED, "guest memory");
    resource = heap_create("resource", 0x50000000, 0x7F000000, 64);
    process = heap_create("process", 0x10000000, 0x30000000, 16);
    Cpu c = {0};
    const uint32_t payload = 180113824, raw = 180113988;
    uint32_t p = request(&c, 74368384, 0x2000, 0x0079EBFF);
    CHECK(heap_owns(resource, p) && !heap_stats(process).allocs, "stock Y00 allocation unchanged");
    release(&c, p);
    p = request(&c, payload, 0x2000, 0x0079EC0F);
    CHECK(heap_owns(resource, p), "other caller unchanged"); release(&c, p);
    p = request(&c, payload, 0x2087, 0x0079EBFF);
    CHECK(heap_owns(resource, p), "other flags unchanged"); release(&c, p);
    p = crt(&c, "malloc", 0x0047668A, raw);
    CHECK(heap_owns(resource, p), "scope restored outside hook"); release(&c, p);

    uint32_t holes[5], pins[5];
    for (int i = 0; i < 5; ++i) {
        holes[i] = gmalloc(128u << 20);
        pins[i] = gmalloc(16u << 20);
    }
    for (int i = 0; i < 5; ++i) gfree(holes[i]);
    uint64_t free_bytes = (752ull << 20) - heap_stats(resource).pages_used * 4096;
    CHECK(free_bytes > raw * 3ull && !heap_alloc(resource, raw), "real resource fragmentation rejects Y00 despite total free");
    unsigned calls = resource_calls;
    uint32_t first = request(&c, payload, 0x2000, 0x0079EBFF);
    CHECK(first && heap_owns(process, first) && heap_size(process, first) == raw, "oversized backing isolated in process heap");
    CHECK(resource_calls == calls + 1, "only native list node uses resource heap");
    CHECK(heap_stats(process).allocs == 1, "one backing reservation");
    G[first] = 0x12; G[first + raw / 2] = 0x34; G[first + raw - 1] = 0x56;
    /* The pins fragmented the heap; free them so an overlap's fallback block fits. */
    for (int i = 0; i < 5; ++i) gfree(pins[i]);
    uint32_t over = request(&c, payload, 0x2000, 0x0079EBFF);
    CHECK(over && over != first && heap_owns(resource, over) && G[first] == 0x12, "overlap takes resource heap, live backing untouched");
    release(&c, over);
    release(&c, first);
    for (int i = 0; i < 2; ++i) {
        p = request(&c, payload, 0x2000, 0x0079EBFF);
        CHECK(p == first && !G[p] && !G[p + raw / 2] && !G[p + raw - 1], "reload reuses zeroed backing");
        G[p] = 1; G[p + raw / 2] = 2; G[p + raw - 1] = 3;
        release(&c, p);
    }
    CHECK(heap_stats(process).allocs == 1 && heap_stats(process).live_bytes == raw, "free retains one reusable reservation");
    p = request(&c, payload + (8u << 20), 0x2000, 0x0079EBFF);
    CHECK(p && heap_size(process, p) == raw + (8u << 20), "larger pack grows process backing");
    CHECK(!G[p] && !G[p + raw / 2] && !G[p + raw - 1], "grown backing is zeroed"); release(&c, p);
    CHECK(heap_check(resource) && heap_check(process) && !heap_stats(resource).bad_frees && !heap_stats(process).bad_frees, "heap integrity and matching frees");
    printf("Y00 HEAP PASS checks=%u total_resource_free=%llu raw=%u reservations=1 reloads=2 bad_frees=0\n", checks, (unsigned long long)free_bytes, raw);
    return 0;
}
