"""Original Deuces/Joker evaluators; wild cards may represent any rank/suit."""
from collections import Counter

STRAIGHTS=tuple(frozenset(range(low,low+5)) for low in range(2,11))+(frozenset((14,2,3,4,5)),)
ROYAL=frozenset((10,11,12,13,14))


def evaluate_game_hand(cards,game):
    cards=tuple(cards)
    if (len(cards)!=5 or len(set(cards))!=5 or
            any(type(c) is not int or not 0<=c<game.deck_size for c in cards)):
        raise ValueError('Five distinct cards from the selected deck are required')
    if game.family=='standard':
        from poker_engine import evaluate_hand
        return evaluate_hand(cards)
    wilds=[c for c in cards if c==52 or (game.family=='deuces' and c%13==0)]
    natural=[c for c in cards if c not in wilds]
    wild=len(wilds)
    ranks=[c%13+2 for c in natural]
    count=Counter(ranks)
    rank_set=frozenset(ranks)
    flush=bool(natural) and len({c//13 for c in natural})==1
    distinct=len(rank_set)==len(ranks)
    straight=distinct and any(rank_set<=window for window in STRAIGHTS)
    if not wild and flush and rank_set==ROYAL:return 'royal_flush'
    if game.family=='deuces' and wild==4:
        return 'four_deuces_ace' if ranks[0]==14 else 'four_deuces'
    # A natural royal and a wild royal are distinct awards in both wild games.
    if wild and flush and distinct and rank_set<=ROYAL:return 'wild_royal'
    if len(count)==1 and max(count.values())+wild==5:
        rank=ranks[0]
        return 'five_aces' if rank==14 else 'five_345' if rank<=5 else 'five_6k'
    if flush and straight:return 'straight_flush'
    maximum=max(count.values())
    if maximum+wild>=4:return 'four_5k'
    if len(count)==2 and maximum+wild>=3:return 'full_house'
    if flush:return 'flush'
    if straight:return 'straight'
    if maximum+wild>=3:return 'three_kind'
    if game.family=='joker':
        if len([r for r,n in count.items() if n==2])==2:return 'two_pair'
        if any(r>=13 and n+wild>=2 for r,n in count.items()):return 'high_pair'
    return 'nothing'
