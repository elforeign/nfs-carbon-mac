            /* The diagnostic ring holds 192 bytes per line. Split the slot
             * counters so even ten-digit counts retain the final collision. */
            n = snprintf(b, sizeof b, " DoFFB %u", carbon_feedback_ticks);
            carbon_feedback_ticks = 0;
            for (int i = 1; i < 6; ++i) if (ncalls[i]) n += snprintf(b + n, sizeof b - n, " %s %u", nm[i], ncalls[i]);
            for (int first = 6; first < 18; first += 6) {
                char extra[180]; int used = 0;
                for (int i = first; i < first + 6; ++i) if (ncalls[i])
                    used += snprintf(extra + used, sizeof extra - used, " %s %u", nm[i], ncalls[i]);
                if (used) diag_event("feedback: calls%s", extra);
            }
