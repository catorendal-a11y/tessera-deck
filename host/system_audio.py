"""The sound and media functions of the system the host runs on (Windows: platform_windows; Linux: platform_linux)."""
from platform_support import IS_LINUX

if IS_LINUX:
    from platform_linux.audio import control_audio, read_audio, read_mixer  # noqa: F401
    from platform_linux.media import MediaReader, control_media  # noqa: F401
else:
    from platform_windows.audio import control_audio, read_audio, read_mixer  # noqa: F401
    from platform_windows.media import MediaReader, control_media  # noqa: F401
