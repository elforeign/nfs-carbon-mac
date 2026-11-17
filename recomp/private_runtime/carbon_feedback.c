/* The selected model owns the feedback API; transport remains separate. */
#include <CommonCrypto/CommonDigest.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int carbon_feedback_image_ok;
int carbon_feedback_image_validate(const void *bytes, size_t size) {
    carbon_feedback_image_ok = 0;
    if (!bytes || !size || size > UINT32_MAX) return 0;
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    char hex[2 * CC_SHA256_DIGEST_LENGTH + 1];
    CC_SHA256(bytes, (CC_LONG)size, digest);
    for (unsigned i = 0; i < sizeof digest; ++i) snprintf(hex + 2 * i, 3, "%02x", digest[i]);
    carbon_feedback_image_ok = !strcmp(hex,
        "baaaaec33873d4ba7e4dbae6a5212049ffdcf9679a35d865d7625b4189952fd3");
    return carbon_feedback_image_ok;
}
#include "feedback.c"
