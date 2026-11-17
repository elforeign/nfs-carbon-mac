"""Required portable scripted/controller input interfaces for the selected target."""


REQUIRED = {'user32.m': {'script_seq', 'user32_script', 'press', 'key_event',
    'di_event', 'user32_di_next', 'pad_apply_layout', 'pad_read_n', 'pad_native'}}


def verify_input(inventory):
    for name, required in REQUIRED.items():
        lost = required & {row['name'] for row in inventory[name]}
        if lost:
            raise ValueError(f'private input quarantined required bodies: {sorted(lost)}')
