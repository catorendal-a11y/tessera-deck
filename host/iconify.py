"""Optional online icon discovery through the public Iconify API (user-initiated, host-side proxy).

The editor never talks to the internet itself: it asks this module, which only reaches api.iconify.design,
validates what comes back and hands the editor plain data. Nothing is requested until the user searches.
Iconify aggregates open-source icon sets with different licenses; the editor tells the user to check them.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.iconify.design'
TIMEOUT_SECONDS = 6
MAX_ICONS = 48
MAX_SVG_BYTES = 64 * 1024
ICON_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,40}:[a-z0-9][a-z0-9-]{0,80}')
COLOR = re.compile(r'#[0-9A-Fa-f]{6}')
FORBIDDEN = re.compile(r'(?i)<\s*(script|foreignObject|iframe|image|use)\b|\bon\w+\s*=|javascript:|xlink:href|href\s*=')


def _fetch(url: str, limit: int, opener=urllib.request.urlopen) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'Tessera-Deck'})
    with opener(request, timeout=TIMEOUT_SECONDS) as reply:
        return reply.read(limit + 1)


def search(query: str, opener=urllib.request.urlopen) -> list[str]:
    """Icon ids like 'mdi:home' matching `query`."""
    query = query.strip()
    if not 2 <= len(query) <= 40:
        raise ValueError('Type at least two letters to search')
    url = f'{API}/search?' + urllib.parse.urlencode({'query': query, 'limit': MAX_ICONS})
    raw = _fetch(url, 256 * 1024, opener)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError('The icon service sent an unreadable answer') from exc
    icons = data.get('icons') if isinstance(data, dict) else None
    if not isinstance(icons, list):
        raise ValueError('The icon service sent an unexpected answer')
    return [icon for icon in icons if isinstance(icon, str) and ICON_ID.fullmatch(icon)][:MAX_ICONS]


def svg(icon_id: str, color: str = '#FFFFFF', opener=urllib.request.urlopen) -> str:
    """The SVG of one icon, drawn in `color` at 144 px, checked to contain nothing but shapes."""
    if not ICON_ID.fullmatch(icon_id or ''):
        raise ValueError('Not a valid icon name')
    if not COLOR.fullmatch(color or ''):
        raise ValueError('The color must look like #RRGGBB')
    prefix, name = icon_id.split(':')
    query = urllib.parse.urlencode({'color': color, 'height': 144})
    raw = _fetch(f'{API}/{prefix}/{name}.svg?{query}', MAX_SVG_BYTES, opener)
    if len(raw) > MAX_SVG_BYTES:
        raise ValueError('The icon is unreasonably large')
    text = raw.decode('utf-8', 'replace').strip()
    if not text.startswith('<svg') or not text.endswith('</svg>') or FORBIDDEN.search(text):
        raise ValueError('The icon service sent something that is not a plain icon')
    return text
