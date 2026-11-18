"""The sound and media functions of the system the host runs on (platform_windows)."""
from platform_support import load

_audio, _media = load('audio'), load('media')
control_audio, read_audio, read_mixer = _audio.control_audio, _audio.read_audio, _audio.read_mixer  # noqa: F401
MediaReader, control_media = _media.MediaReader, _media.control_media  # noqa: F401
