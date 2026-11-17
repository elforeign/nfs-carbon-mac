/* 00588CA0 switches the native language and loads GLOBAL / FRONTEND / INGAME
 * packs through 005782A0. A5EAC0..A5EC2C is the thirteen-entry native table.
 * Leave unload (-1) and the Retail choice alone. Never offer a partial pack. */
#include "host.h"
#include "settings.h"
#include <CoreFoundation/CoreFoundation.h>
#include <dirent.h>
#include <strings.h>
#include <sys/stat.h>

static const struct { int id; const char *name, *locale; } cadd_languages[] = {
    {0,"English","en"}, {1,"French","fr"}, {2,"German","de"},
    {3,"Italian","it"}, {4,"Spanish","es"}, {5,"Dutch","nl"},
    {6,"Swedish","sv"}, {17,"Polish","pl"}, {18,"Finnish","fi"},
    {7,"Danish","da"}, {8,"Hungarian","hu"}, {9,"Czech","cs"},
    {10,"Mexican","es-MX"},
};
static const char *cadd_language_choices[15] = {"Retail", "Auto (Mac)"};
static const char *cadd_language_values[15] = {"retail", "auto"};
static int cadd_language_indices[15];
static Setting cadd_language_row = {
    .id="gameplay.language", .category=SET_GAMEPLAY, .order=90, .label="Text language",
    .help="Retail keeps the game's language. Auto follows the Mac's installed language choices. Restart to apply.",
    .type=SET_CHOICE, .choices=cadd_language_choices, .values=cadd_language_values,
    .nchoices=2, .restart=1, .env="NFS_CARBON_LANGUAGE"
};

static int cadd_pack_present(const char *name) {
    if (!game_dir) return 0;
    char folder[2048];
    if (snprintf(folder,sizeof folder,"%s/LANGUAGES",game_dir) >= (int)sizeof folder) return 0;
    DIR *dir = opendir(folder);
    if (!dir) return 0;
    unsigned mask = 0;
    static const char *const suffix[] = {"Global", "Frontend", "InGame"};
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        for (unsigned i = 0; i < 3; ++i) {
            char wanted[128]; snprintf(wanted,sizeof wanted,"%s_%s.bin",name,suffix[i]);
            if (strcasecmp(wanted,entry->d_name)) continue;
            char path[2304]; struct stat st;
            if (snprintf(path,sizeof path,"%s/%s",folder,entry->d_name) < (int)sizeof path &&
                !stat(path,&st) && S_ISREG(st.st_mode) && st.st_size > 0) mask |= 1u << i;
        }
    }
    closedir(dir);
    return mask == 7;
}

void carbon_addons_language_init(void) {
    for (unsigned i = 0; i < sizeof cadd_languages / sizeof *cadd_languages; ++i) {
        if (!cadd_pack_present(cadd_languages[i].name)) continue;
        int n = cadd_language_row.nchoices++;
        cadd_language_choices[n] = cadd_language_values[n] = cadd_languages[i].name;
        cadd_language_indices[n] = (int)i;
    }
    settings_add(&cadd_language_row);
}

static int cadd_auto_language(void) {
    CFArrayRef preferred = CFLocaleCopyPreferredLanguages();
    int selected = -1;
    for (CFIndex p = 0; preferred && p < CFArrayGetCount(preferred) && selected < 0; ++p) {
        char locale[128];
        if (!CFStringGetCString(CFArrayGetValueAtIndex(preferred,p),locale,sizeof locale,kCFStringEncodingUTF8)) continue;
        /* Mexican precedes the general Spanish match for es-MX. */
        for (int n = cadd_language_row.nchoices - 1; n >= 2; --n) {
            int i = cadd_language_indices[n]; size_t len = strlen(cadd_languages[i].locale);
            if (!strncasecmp(locale,cadd_languages[i].locale,len) &&
                (!locale[len] || locale[len]=='-' || locale[len]=='_')) { selected = cadd_languages[i].id; break; }
        }
    }
    if (preferred) CFRelease(preferred);
    if (selected < 0 && cadd_pack_present("English")) selected = 0;
    return selected;
}

void carbon_addons_language(Cpu *c, void (*original)(Cpu *)) {
    uint32_t address = c->esp + 4, saved = M32(address);
    int choice = cadd_language_row.boot_value, language = -1;
    if ((int32_t)saved >= 0) {
        if (choice == 1) language = cadd_auto_language();
        else if (choice >= 2 && choice < cadd_language_row.nchoices)
            language = cadd_languages[cadd_language_indices[choice]].id;
    }
    if (language >= 0) M32(address) = (uint32_t)language;
    original(c);
    M32(address) = saved;
}
