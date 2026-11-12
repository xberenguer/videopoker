#!/usr/bin/env python3
"""Independent rank/suit enumeration and physical draw checks for wild games.

Wild replacements are exhaustively assigned ranks. Suit multiplicities count
all physical terminal hands without visiting millions of equivalent hands.
This oracle never calls the production evaluator, category counts or solver.
"""
from collections import Counter
from itertools import combinations,combinations_with_replacement
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import get_game
from poker_evaluate import evaluate_game_hand
from poker_cabinet_strategy import GameStrategyTable

# Independent literal awards and ranking order. Ties choose the higher poker
# category, as the pay screen does (not the larger future multiplier).
ORACLE_PAY={
 'deuces':dict(royal_flush=800,four_deuces_ace=400,four_deuces=200,
               five_aces=80,five_345=40,five_6k=20,wild_royal=25,
               straight_flush=9,four_5k=4,full_house=4,flush=3,straight=1,three_kind=1,nothing=0),
 'joker':dict(royal_flush=800,five_aces=200,five_345=200,five_6k=200,
              wild_royal=100,straight_flush=50,four_5k=15,full_house=7,
              flush=5,straight=3,three_kind=2,two_pair=1,high_pair=1,nothing=0),
}
PRIORITY=('royal_flush','four_deuces_ace','four_deuces','wild_royal',
          'five_aces','five_345','five_6k','straight_flush','four_5k',
          'full_house','flush','straight','three_kind','two_pair','high_pair','nothing')


def pattern_oracle(natural,wild,flush,family):
    if family=='deuces' and wild==4:
        return 'four_deuces_ace' if natural==(14,) else 'four_deuces'
    candidates={'nothing'}
    for replacement in combinations_with_replacement(range(2,15),wild):
        ranks=tuple(sorted(natural+replacement))
        counts=sorted((ranks.count(r) for r in set(ranks)),reverse=True)
        is_straight=(len(set(ranks))==5 and
                     (ranks[-1]-ranks[0]==4 or ranks==(2,3,4,5,14)))
        royal=ranks==(10,11,12,13,14)
        if flush and royal:candidates.add('wild_royal' if wild else 'royal_flush')
        if counts[0]==5:
            candidates.add('five_aces' if ranks[0]==14 else 'five_345' if ranks[0]<=5 else 'five_6k')
        if flush and is_straight:candidates.add('straight_flush')
        if counts[0]==4:candidates.add('four_5k')
        if counts==[3,2]:candidates.add('full_house')
        if flush:candidates.add('flush')
        if is_straight:candidates.add('straight')
        if counts[0]==3:candidates.add('three_kind')
        if family=='joker':
            if counts==[2,2,1]:candidates.add('two_pair')
            if any(r>=13 and ranks.count(r)>=2 for r in set(ranks)):candidates.add('high_pair')
    return max(candidates,key=lambda c:(ORACLE_PAY[family][c],-PRIORITY.index(c)))


def physical_oracle(cards,family):
    naturals=tuple(sorted(c%13+2 for c in cards if c!=52 and not(family=='deuces' and c%13==0)))
    wild=5-len(naturals)
    suits={c//13 for c in cards if c!=52 and not(family=='deuces' and c%13==0)}
    return pattern_oracle(naturals,wild,len(suits)==1,family)


def terminal_counts(family):
    counts=Counter();patterns=0
    ranks=range(3,15) if family=='deuces' else range(2,15)
    max_wild=4 if family=='deuces' else 1
    for wild in range(max_wild+1):
        wild_ways=math.comb(4,wild) if family=='deuces' else 1
        for natural in combinations_with_replacement(ranks,5-wild):
            multiplicity=Counter(natural)
            if max(multiplicity.values())>4:continue
            ways=wild_ways*math.prod(math.comb(4,n) for n in multiplicity.values())
            flush_ways=4*wild_ways if len(multiplicity)==len(natural) else 0
            if flush_ways:
                counts[pattern_oracle(natural,wild,True,family)]+=flush_ways;patterns+=1
            if ways>flush_ways:
                counts[pattern_oracle(natural,wild,False,family)]+=ways-flush_ways;patterns+=1
    return counts,patterns


def main():
    started=time.monotonic();results={}
    output=ROOT/'validation/cabinet';output.mkdir(exist_ok=True)
    rng=random.Random(194017)
    for family,game_id in (('deuces','dwb10'),('joker','joker5')):
        g=get_game(game_id);table=GameStrategyTable(game_id)
        expected,patterns=terminal_counts(family)
        observed=struct.unpack_from('<'+str(len(g.categories))+'I',table.raw,64)
        for key,count in zip(g.categories,observed):
            assert count==expected.get(key,0),(family,key,count,expected.get(key,0))
        assert sum(expected.values())==math.comb(g.deck_size,5)
        fixtures=([0,13,26,39,12],[0,13,26,8,12],[0,13,8,9,12],
                  [0,8,9,10,12],[0,1,14,27,40],[0,1,14,2,15]) if family=='deuces' else (
                  [52,12,25,38,51],[52,8,9,10,12],[52,11,24,0,2],
                  [52,9,22,0,2],[52,0,1,2,3],[52,0,13,1,14])
        per_hand_checks=0
        for hand in list(fixtures)+[rng.sample(range(g.deck_size),5) for _ in range(1000)]:
            actual=evaluate_game_hand(hand,g);want=physical_oracle(hand,family)
            assert actual==want,(family,hand,actual,want)
            per_hand_checks+=1
        conditional=[]
        for hand in fixtures[:3]:
            histograms=table.counts(hand)
            remaining=[c for c in range(g.deck_size) if c not in hand]
            masks=[31^(1<<i) for i in range(5)]+[0b00111,0b11001]
            for mask in masks:
                held=[c for i,c in enumerate(hand) if mask&(1<<i)]
                count=Counter(physical_oracle(held+list(draw),family)
                              for draw in combinations(remaining,5-len(held)))
                actual=dict(zip(g.categories,histograms[mask]))
                assert all(actual[c]==count.get(c,0) for c in g.categories),(family,hand,mask)
                conditional.append({'hand':hand,'mask':mask,'physical_completions':sum(count.values())})
        results[family]={'status':'PASS','all_physical_terminal_hands':sum(expected.values()),
                         'weighted_rank_suit_patterns':patterns,'terminal_category_counts':dict(expected),
                         'per_hand_oracle_checks':per_hand_checks,'conditional_draw_checks':conditional,
                         'table_sha256':hashlib.sha256(table.raw).hexdigest()}
        (output/'independent-wild-math.json').write_text(json.dumps({'status':'IN_PROGRESS',**results},indent=2)+'\n')
        print('PASS '+family+' '+str(sum(expected.values()))+' terminal hands; '+str(len(conditional))+' physical draw checks',flush=True)
    report={'schema':1,'status':'PASS','method':__doc__,'families':results,
            'oracle_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'duration_seconds':time.monotonic()-started,'physical_hardware_tested':False}
    (output/'independent-wild-math.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Independent wild math complete',flush=True)


if __name__=='__main__':main()
