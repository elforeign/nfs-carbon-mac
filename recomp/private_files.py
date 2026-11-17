"""Required native file routing and read-only track overlay interfaces."""


def verify_files(inventory):
    required = {'win32', 'resolve', 'private_resolve', 'file_open', 'handle_fd',
                'file_close', 'file_write', 'file_flush', 'file_end', 'file_flags',
                'private_track_overlay_init', 'private_track_overlay_path'}
    lost = required & {r['name'] for r in inventory['boot.c']}
    if lost:
        raise ValueError('private file API quarantined: ' + ', '.join(sorted(lost)))
