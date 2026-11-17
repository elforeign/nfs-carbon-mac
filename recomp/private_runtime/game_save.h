/* Selected native save admission and completion policy. */
static inline int game_save_allowed(void) { return 1; }
static inline int game_save_prepare(const char *path) { (void)path; return 1; }
static inline void game_save_complete(int committed) { (void)committed; }
static inline int game_backup_before_write(const char *destination, const char *staged) {
    (void)destination; (void)staged; return 1;
}
