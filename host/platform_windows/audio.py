"""Speaker, microphone and per-program volume on Windows (Core Audio through pycaw), and the mixer of the status screen."""
from __future__ import annotations

from pc_state import APP_TARGET, check_audio


def _endpoints() -> dict:
    """Default speaker and microphone endpoint volume interfaces (call between CoInitialize/Uninitialize)."""
    try:
        from comtypes import CLSCTX_ALL, COMError
        from pycaw.api.endpointvolume import IAudioEndpointVolume
        from pycaw.constants import EDataFlow, ERole
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise OSError(f'audio control is not installed: {exc}') from exc
    enumerator = AudioUtilities.GetDeviceEnumerator()

    def endpoint(flow):
        device = enumerator.GetDefaultAudioEndpoint(flow.value, ERole.eMultimedia.value)
        return device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)

    try:
        mic = endpoint(EDataFlow.eCapture)
    except COMError:  # no microphone: the speaker and the mixer still work
        mic = None
    return {'speaker': endpoint(EDataFlow.eRender), 'mic': mic}


def _with_audio(work):
    try:
        import comtypes
    except ImportError as exc:
        raise OSError(f'audio control is not installed: {exc}') from exc
    comtypes.CoInitialize()
    try:
        return work(_endpoints())
    except comtypes.COMError as exc:
        raise OSError(f'no audio device: {exc}') from exc
    finally:
        comtypes.CoUninitialize()


def read_audio() -> dict:
    """Default speaker volume/mute and default microphone mute; raises OSError when unavailable."""
    return _with_audio(lambda ends: {
        'volume': round(ends['speaker'].GetMasterVolumeLevelScalar() * 100),
        'speaker_muted': bool(ends['speaker'].GetMute()), 'mic_muted': ends['mic'] is not None and bool(ends['mic'].GetMute())})


class _Control:
    """The four calls the audio operations need, for a device endpoint or one app's audio session."""

    def __init__(self, get_mute, set_mute, get_volume, set_volume):
        self.get_mute, self.set_mute, self.get_volume, self.set_volume = get_mute, set_mute, get_volume, set_volume


def apply_operation(control: _Control, operation: str, value: int | None = None, step: int = 5) -> None:
    if operation in ('toggle', 'mute', 'unmute'):
        muted = (not control.get_mute()) if operation == 'toggle' else operation == 'mute'
        control.set_mute(int(muted), None)
        return
    current = round(control.get_volume() * 100)
    target = value if operation == 'volume' else current + (step if operation == 'up' else -step)
    control.set_volume(max(0, min(100, target)) / 100, None)


def _all_sessions() -> list:
    """The audio sessions on every active output device: a program can play on a device other than the default one."""
    from comtypes import CLSCTX_ALL, COMError
    from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.pycaw import AudioSession, AudioUtilities
    devices = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
    sessions = []
    for index in range(devices.GetCount()):
        try:
            manager = devices.Item(index).Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
            found = manager.GetSessionEnumerator()
            for number in range(found.GetCount()):
                control = found.GetSession(number).QueryInterface(IAudioSessionControl2)
                if control is not None:
                    sessions.append(AudioSession(control))
        except COMError:  # a device that cannot be opened must not hide the programs on the others
            continue
    return sessions


def _app_controls(name: str) -> list[_Control]:
    controls = []
    for session in _all_sessions():
        process = session.Process
        if process is not None and process.name().casefold() == name.casefold():
            volume = session.SimpleAudioVolume
            controls.append(_Control(volume.GetMute, volume.SetMute, volume.GetMasterVolume, volume.SetMasterVolume))
    return controls


def control_audio(target: str, operation: str = 'toggle', value: int | None = None, step: int = 5) -> None:
    """Mute, unmute, toggle or set the volume of the speakers, the microphone or one program's sound."""
    check_audio({'target': target, 'op': operation, **({'value': value} if value is not None else {}), 'step': step})
    app = APP_TARGET.fullmatch(target)
    if app:
        try:
            import comtypes
        except ImportError as exc:
            raise OSError(f'audio control is not installed: {exc}') from exc
        comtypes.CoInitialize()
        try:
            controls = _app_controls(app.group(1))
            if not controls:
                raise OSError(f'{app.group(1)} is not playing sound right now')
            if operation == 'toggle':  # one decision for every session of the program, so a mixed state converges
                operation = 'unmute' if all(control.get_mute() for control in controls) else 'mute'
            for control in controls:
                apply_operation(control, operation, value, step)
        finally:
            comtypes.CoUninitialize()
        return

    def apply(ends):
        endpoint = ends[target]
        if endpoint is None:
            raise OSError('no microphone is connected')
        apply_operation(_Control(endpoint.GetMute, endpoint.SetMute, endpoint.GetMasterVolumeLevelScalar,
                                 endpoint.SetMasterVolumeLevelScalar), operation, value, step)

    _with_audio(apply)


def read_mixer(pinned: list | None = None, mic: bool = True) -> list[dict]:
    """The default speaker, up to three programs and the microphone. Raises OSError without audio.

    `pinned` names the programs to show (those that have a sound session right now); without it the programs that
    play sound are chosen."""
    from cockpit import APP_COLORS, GREEN, MAX_APPS, MAX_ID, app_title

    def work(ends):
        speaker, mic_end = ends['speaker'], ends['mic']
        apps = {}
        for session in _all_sessions():
            process = session.Process
            if process is None:
                continue
            name = process.name()
            if name.lower() in apps or not APP_TARGET.fullmatch('app:' + name) or len(name) + 4 > MAX_ID:
                continue
            volume = session.SimpleAudioVolume
            apps[name.lower()] = {'id': 'app:' + name, 'name': app_title(name), 'active': int(session.State) == 1,
                                  'level': round(volume.GetMasterVolume() * 100), 'muted': bool(volume.GetMute())}
        # Programs that are playing right now come first; the ones shown keep alphabetical order so they do not jump.
        if pinned:
            wanted = [name.lower() for name in pinned][:MAX_APPS]
            chosen = [apps[name] for name in wanted if name in apps]
        else:
            chosen = sorted(sorted(apps.values(), key=lambda app: (not app['active'], app['name'].lower()))[:MAX_APPS],
                            key=lambda app: app['name'].lower())
        faders = [{'id': 'speaker', 'name': 'Master', 'level': round(speaker.GetMasterVolumeLevelScalar() * 100),
                   'muted': bool(speaker.GetMute()), 'color': GREEN}]
        faders += [{'id': app['id'], 'name': app['name'], 'level': app['level'], 'muted': app['muted'],
                    'color': APP_COLORS[index]} for index, app in enumerate(chosen)]
        if mic and mic_end is not None:  # no microphone: the mixer shows the speaker and the programs only
            faders.append({'id': 'mic', 'name': 'Mic', 'level': round(mic_end.GetMasterVolumeLevelScalar() * 100),
                           'muted': bool(mic_end.GetMute()), 'mic': True, 'color': '#4DD0E1'})
        return faders

    return _with_audio(work)
