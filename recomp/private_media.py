"""Required shared audio/input interfaces for the selected target."""


REQUIRED={'dsound.c':{
    'dsound_mix_rms','dsound_mix_levels','private_mix_buffers',
    'win32_dsound','new_obj','obj','make_vtable','d_QueryInterface','d_AddRef','d_Release',
    'd_CreateSoundBuffer','d_GetCaps','d_DuplicateSoundBuffer','d_SetCooperativeLevel',
    'd_GetSpeakerConfig','d_SetSpeakerConfig','b_GetCaps','b_GetCurrentPosition','b_GetFormat',
    'b_GetVolume','b_GetPan','b_GetFrequency','b_GetStatus','b_Lock','b_Unlock','b_Play',
    'b_Stop','b_SetCurrentPosition','b_SetFormat','b_SetVolume','b_SetPan','b_SetFrequency',
    'b_Restore','n_SetNotificationPositions'},
    'dinput.c':{
    'win32_dinput','i_CreateDevice','i_EnumDevices','i_GetDeviceStatus','d_GetCapabilities',
    'd_EnumObjects','d_GetProperty','d_SetProperty','d_Acquire','d_Unacquire','d_GetDeviceState',
    'd_GetDeviceData','d_SetDataFormat','d_SetEventNotification','d_SetCooperativeLevel',
    'd_GetDeviceInfo','d_Poll','d_GetObjectInfo'},'boot.c':{'win32'}}


def verify_media(inventory):
    for name,required in REQUIRED.items():
        lost=required & {row['name'] for row in inventory[name]}
        if lost:raise ValueError(f'private audio/input quarantined required bodies in {name}: {sorted(lost)}')
