#!/usr/bin/env python3
"""Enumerate selected-deck outcomes and solve each cabinet game's own policy."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_games import GAMES,get_game


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games',nargs='+',default=['ddb10']+[g.id for g in GAMES if g.id!='ddb10'])
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--keep-cache',action='store_true')
    args=parser.parse_args()
    build=ROOT/'validation/cabinet/strategy-build';build.mkdir(parents=True,exist_ok=True)
    source=ROOT/'native/cabinet_strategy_tables.cpp'
    source_hash=digest(source)
    runtime=ROOT/'payload/opt/dino/strategy'
    output=runtime/'cabinet';output.mkdir(exist_ok=True)
    binaries={}
    results={}
    for game_id in args.games:
        game=get_game(game_id)
        family={'standard':0,'deuces':1,'joker':2}[game.family]
        if family not in binaries:
            binary=build/('solver-'+game.family)
            subprocess.run(['clang++','-O3','-std=c++17','-pthread','-Wall','-Wextra',
                            '-DCAB_FAMILY='+str(family),str(source),'-o',str(binary)],check=True)
            binaries[family]=binary
        folder=build/game.id;folder.mkdir(exist_ok=True)
        config=(str(game.hands)+' '+str(len(game.categories))+' '+str(game.deck_size)+'\n'+
                ' '.join(map(str,game.pays))+'\n'+' '.join(map(str,game.multipliers))+'\n')
        config_hash=hashlib.sha256(config.encode()).hexdigest()
        stamp=folder/'input-binding.json'
        binding={'generator_sha256':source_hash,'config_sha256':config_hash}
        if stamp.exists() and json.loads(stamp.read_text())!=binding:
            raise RuntimeError('Inputs changed; preserve old evidence and use a fresh build folder: '+str(folder))
        stamp.write_text(json.dumps(binding,indent=2)+'\n')
        (folder/'config.txt').write_text(config)
        count_name='subset_counts.dat' if family==0 else game.family+'_counts.dat'
        counts=runtime/count_name
        subset=folder/'subset_counts.dat'
        if counts.exists() and not subset.exists():os.link(counts,subset)
        print('START '+game.id,flush=True)
        if not (folder/'bias.json').exists():
            with (folder/'build.log').open('w') as log:
                subprocess.run([str(binaries[family]),'--output',str(folder),'--config',str(folder/'config.txt'),
                                '--threads',str(args.threads),'--max-iterations','100','--tolerance','1e-9'],
                               check=True,stdout=log,stderr=subprocess.STDOUT)
        raw=subset.read_bytes()
        sections=[];offset=64
        for k in range(5):
            width=4 if k<2 else 2 if k<4 else 1
            rows=math.comb(game.deck_size,k)
            sections.append({'subset_size':k,'offset':offset,'rows':rows,'width':width})
            offset+=rows*len(game.categories)*width
        assert len(raw)==offset
        assert struct.unpack_from('<8s6I4Q',raw)==(b'UXSUB01\0',1,64,len(game.categories),game.deck_size,4,0,64,len(raw)-64,0,0)
        bias=json.loads((folder/'bias.json').read_text())
        cert=json.loads((folder/'policy-certificate.json').read_text())
        assert bias['num_hands']==game.hands and 0<=bias['bellman_span']<=1e-6
        for key in ('stationary_norm_error','stationary_residual','transition_row_error','poisson_span'):
            assert abs(cert[key])<1e-6,(game_id,key,cert[key])
        assert cert['bias_comparison_max_error']<1e-5
        if not counts.exists():shutil.copy2(subset,counts)
        assert digest(counts)==hashlib.sha256(raw).hexdigest()
        meta={'schema':2,'game_id':game.id,'title':game.title,'family':game.family,'num_hands':game.hands,
              'deck_size':game.deck_size,'category_order':list(game.categories),'payouts':list(game.pays),
              'multiplier_order':list(game.multipliers),'low_coin':dict(game.low_coin),
              'counts_file':count_name,'table_sha256':digest(counts),'table_bytes':len(raw),
              'sections':sections,'bias':bias,'policy_certificate':cert,
              'method':'Exact integer terminal/subset enumeration and suit-orbit weighting; next-multiplier convolution; average-reward Bellman iteration; independent Markov policy evaluation',
              'arithmetic':'IEEE754 doubles; long double policy accumulation; numerical certificate, no interval proof',
              'generator_sha256':source_hash,'game_config_sha256':config_hash,
              'reference_pay_screen':('docs/images/south-point-ddb-75.jpg' if game.id=='ddb10_75' else
                                      None if '_' in game.id else 'validation/cabinet/reference/'+game.id+'-paytable.png'),
              'reference_url':None if '_' in game.id else 'https://www.videopoker.com/play/?game=69&title=Ultimate%20X%20Poker',
              'reference_note':('User-supplied South Point photo; exact ten-hand payout and multiplier vectors.' if game.id=='ddb10_75' else
                                'Numerically specified alternate DDB full-house/flush awards; original hand-count multiplier schedule. No casino location claimed.' if '_' in game.id else 'Original reference cabinet preset.'),
              'physical_timing_qualified':False}
        target=output/(game.id+'.json');target.write_text(json.dumps(meta,indent=2)+'\n')
        results[game.id]={'status':'PASS','metadata_sha256':digest(target),'table_sha256':meta['table_sha256'],
                         'return':cert['return'],'bellman_span':bias['bellman_span'],
                         'num_hands':game.hands,'deck_size':game.deck_size}
        (build/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        # Only the derived cache created by this build is removed; every
        # configuration, log, table and certificate remains reproducible.
        cache=folder/'canonical_counts.dat'
        if cache.exists() and not args.keep_cache:
            (folder/'canonical-cache.sha256').write_text(digest(cache)+'  '+cache.name+'\n')
            cache.unlink()
        print('PASS '+game.id+' '+json.dumps(results[game.id]),flush=True)
    if source_hash!=digest(source):raise RuntimeError('Generator changed during build')


if __name__=='__main__':main()
