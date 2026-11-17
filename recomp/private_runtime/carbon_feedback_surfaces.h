/* Native curves include inheritance and the image's own surface collection
 * layout. No synthetic surface or foreign attribute-class binding is installed. */
static int is_rough(Cpu *c, uint32_t surf) { (void)c; (void)surf; return 0; }
static uint32_t test_surface(Cpu *c, uint32_t surf) { (void)c; return surf; }
static uint32_t thiscall1(Cpu *c, uint32_t self, uint32_t fn, uint32_t a0);
