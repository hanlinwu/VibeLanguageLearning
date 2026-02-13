from __future__ import annotations

from urllib.parse import quote


def generate_avatar_url(seed: str, nonce: str = '') -> str:
    base_seed = (seed or 'user').strip()
    full_seed = f'{base_seed}-{nonce}'.strip('-')
    encoded = quote(full_seed, safe='')
    # DiceBear public avatar API (no key required).
    return f'https://api.dicebear.com/9.x/bottts-neutral/svg?seed={encoded}'

