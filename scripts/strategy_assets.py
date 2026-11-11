"""Non-executing validation of the bounded, exhaustive strategy resources."""
import hashlib
import json
import math
import struct

PREFIX = 'opt/dino/strategy/'
CATEGORIES = ['royal_flush', 'straight_flush', 'four_aces_kicker',
              'four_234_kicker', 'four_aces', 'four_234', 'four_5k',
              'full_house', 'flush', 'straight', 'three_kind', 'two_pair',
              'high_pair', 'nothing']
PAYOUTS = [800, 50, 400, 160, 160, 80, 50, 9, 6, 4, 3, 1, 1, 0]
MULTIPLIERS = [4, 4, 4, 4, 4, 4, 3, 12, 10, 8, 4, 3, 2, 1]


def validate_strategy_inventory(files):
    raw = files.get(PREFIX+'subset_counts.dat')
    description = files.get(PREFIX+'strategy.json')
    if (raw is None or len(raw) != 4449110 or description is None
            or not 1 <= len(description) <= 100000):
        raise ValueError('Missing or oversized strategy resources')
    try:
        metadata = json.loads(description.decode('utf-8'))
    except (UnicodeError, ValueError) as error:
        raise ValueError('Invalid strategy metadata') from error
    digest = hashlib.sha256(raw).hexdigest()
    if (not isinstance(metadata, dict) or metadata.get('schema') != 1
            or metadata.get('category_order') != CATEGORIES
            or metadata.get('payouts') != PAYOUTS
            or metadata.get('multiplier_order') != MULTIPLIERS
            or metadata.get('table_sha256') != digest
            or struct.unpack_from('<8s6I4Q', raw) !=
            (b'UXSUB01\0', 1, 64, 14, 52, 4, 0, 64, 4449046, 0, 0)):
        raise ValueError('Strategy data is not bound to this game')
    reachable = {0}
    for _ in range(10):
        reachable = {s+m for s in reachable for m in (1, 2, 3, 4, 8, 10, 12)}
    bias = metadata.get('bias', {})
    if (not isinstance(bias, dict) or bias.get('num_hands') != 10
            or bias.get('states') != sorted(reachable)
            or not isinstance(bias.get('values'), list)
            or len(bias['values']) != len(reachable)
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bias['values'])
            or type(bias.get('bellman_span')) not in (int, float)
            or not math.isfinite(bias['bellman_span'])
            or not 0 <= bias['bellman_span'] <= 0.000001):
        raise ValueError('Uncertified strategy continuation values')
    return {'table_sha256': digest, 'table_bytes': len(raw),
            'metadata_sha256': hashlib.sha256(description).hexdigest(),
            'states': len(reachable), 'bellman_span': bias['bellman_span']}
