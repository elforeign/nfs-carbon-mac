/* 0079EBFA requests section 2500 with 00477230(size, 0x2000). Keep the
 * native pool headers, alignment, lists and frees; isolate only its oversized
 * CRT backing block. Stock packs stay on the original resource heap path.
 * Guest execution owns the guest lock; the scope is local to its thread.
 */
static _Thread_local uint32_t carbon_y00_request;
static uint32_t carbon_y00_backing, carbon_y00_capacity;
static int carbon_y00_live;

void carbon_y00_allocate(Cpu *c, void (*original)(Cpu *)) {
    uint32_t size = arg(c, 0), saved = carbon_y00_request;
    /* 00476B20 adds 20 bytes; 00476560 rounds to four and adds 16+128.
     * The caller and flags distinguish Y00 from other pool-0 allocations. */
    carbon_y00_request = M32(c->esp) == 0x0079EBFFu && arg(c, 1) == 0x2000u &&
                         size > 0x08000000u && size <= UINT32_MAX - 167u
                         ? ((size + 23u) & ~3u) + 144u : 0;
    original(c);
    carbon_y00_request = saved;
}

static uint32_t carbon_y00_process(Cpu *c, const char *fn, uint32_t size) {
    /* Use a copied CPU and unused stack below ESP, as for nested imports.
     * The real process heap supplies disjoint guest memory and diagnostics. */
    Cpu heap = *c;
    heap.esp -= 20;
    M32(heap.esp) = 0;
    win32_heap(&heap, "GetProcessHeap");
    uint32_t handle = heap.eax;
    heap.esp -= 4;
    M32(heap.esp + 4) = handle;
    M32(heap.esp + 8) = 0;
    M32(heap.esp + 12) = carbon_y00_backing ? carbon_y00_backing : size;
    if (carbon_y00_backing) M32(heap.esp + 16) = size;
    win32_heap(&heap, fn);
    return heap.eax;
}

static uint32_t carbon_y00_malloc(Cpu *c, uint32_t size) {
    /* 00476684 is the backing malloc; the preceding 16-byte list node is
     * deliberately still an ordinary resource allocation. */
    if (!carbon_y00_request || size != carbon_y00_request || M32(c->esp) != 0x0047668Au)
        return gmalloc(size);
    /* Only one Y00 read may own this storage. Never overwrite a live read: an
     * overlap takes the ordinary resource heap (the game does not check for 0). */
    if (carbon_y00_live) return gmalloc(size);
    if (size > carbon_y00_capacity) {
        uint32_t block = carbon_y00_process(c, carbon_y00_backing ? "HeapReAlloc" : "HeapAlloc", size);
        if (!block) return gmalloc(size);
        carbon_y00_backing = block;
        carbon_y00_capacity = size;
        /* HeapReAlloc keeps the old bytes; callers expect zeroed memory. */
        memset(G + carbon_y00_backing, 0, size);
    } else {
        memset(G + carbon_y00_backing, 0, size);
    }
    carbon_y00_live = 1;
    if (diag_on) diag_event("Y00 backing acquire base=%08x size=%u capacity=%u", carbon_y00_backing, size, carbon_y00_capacity);
    return carbon_y00_backing;
}

static void carbon_y00_free(uint32_t block) {
    if (block && block == carbon_y00_backing) {
        carbon_y00_live = 0;
        if (diag_on) diag_event("Y00 backing release base=%08x capacity=%u", block, carbon_y00_capacity);
    } else {
        gfree(block);
    }
}

static uint32_t carbon_y00_size(uint32_t block) {
    extern uint32_t gmalloc_size(uint32_t);
    return block && block == carbon_y00_backing ? carbon_y00_capacity : gmalloc_size(block);
}
