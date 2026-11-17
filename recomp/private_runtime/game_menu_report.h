/* This menu has no issue-report preview. */
static inline int report_github_active(void) { return 0; }
static inline void report_github_close(void) {}
static inline void report_github_key_event(int k, int d, int r) { (void)k; (void)d; (void)r; }
static inline void report_github_pad_release(uint32_t p) { (void)p; }
static inline void report_github_key(int key) { (void)key; }
static inline void report_github_pad(int d, uint32_t e) { (void)d; (void)e; }
static inline void report_github_mouse(int k, double x, double y, double s) { (void)k; (void)x; (void)y; (void)s; }
static inline void report_github_draw(CGContextRef c, double h, CGRect v, int x) { (void)c; (void)h; (void)v; (void)x; }
