#!/usr/bin/env python3
"""Deterministic, explicitly curated difficulty drills, never normal deals."""
import argparse
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import GAMES
from poker_training import DetailedTable, TOLERANCE
from poker_cabinet_strategy import freeze_round


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--per-level',type=int,default=8)
    args=parser.parse_args()
    rng=random.Random(0x5650545241494E)
    result={}
    # DDB10 is generated first so its training path can be qualified first.
    games=sorted(GAMES,key=lambda g:g.id!='ddb10')
    table=DetailedTable()
    for game in games:
        levels={'close':[],'clear':[]};attempts=0
        while min(map(len,levels.values()))<args.per_level and attempts<3000:
            attempts+=1
            cards=rng.sample(range(game.deck_size),5)
            snap={'phase':'hold','game_id':game.id,'initial':cards,'round_feature':True,
                  'round_base_bet':5,'round_num_hands':game.hands,'active_multipliers':[1]*game.hands}
            report=table.advise(freeze_round(snap))
            worse=[r['value'] for r in report['holds'] if report['value']-r['value']>TOLERANCE]
            gap=(report['value']-max(worse))/(10*game.hands) if worse else 0
            level='close' if 0<gap<=.002 else 'clear' if gap>=.02 else None
            if level and len(levels[level])<args.per_level:
                levels[level].append({'game_id':game.id,'cards':cards,'multipliers':[1]*game.hands,
                    'best':report['mask'],'gap_per_wager':gap,'chosen':0,'loss':max(gap,1e-8)})
        if min(map(len,levels.values()))<args.per_level:
            raise RuntimeError('Insufficient qualified drills for '+game.id)
        result[game.id]=levels
        print(game.id,{k:len(v) for k,v in levels.items()},'candidates',attempts,flush=True)
    (ROOT/'payload/opt/dino/training_drills.json').write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n')


if __name__=='__main__':main()
