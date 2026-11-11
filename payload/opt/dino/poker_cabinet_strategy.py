"""Game-bound exhaustive advice for all twelve Ultimate X cabinet modes.

Only the current game's table stays resident. Advice runs in the existing
cancellable worker, and sees the public dealt hand and frozen round settings.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import time

from poker_games import get_game
from poker_evaluate import evaluate_game_hand
from poker_strategy import StrategyAdvisor,StrategyError,_check_cancel

CHOOSE=tuple(tuple(math.comb(n,k) if n>=k else 0 for k in range(6)) for n in range(54))


def freeze_round(snapshot):
    if not isinstance(snapshot,dict) or snapshot.get('phase')!='hold':
        raise StrategyError('Deal a hand before asking for advice')
    try:game=get_game(snapshot.get('game_id','ddb10'))
    except ValueError as error:raise StrategyError('Invalid game') from error
    hand=snapshot.get('initial')
    if (not isinstance(hand,(tuple,list)) or len(hand)!=5 or
            any(type(c) is not int or not 0<=c<game.deck_size for c in hand) or len(set(hand))!=5):
        raise StrategyError('Invalid dealt hand')
    feature,base,hands=(snapshot.get(k) for k in ('round_feature','round_base_bet','round_num_hands'))
    multipliers=snapshot.get('active_multipliers')
    if (type(feature) is not bool or type(base) is not int or not 1<=base<=5 or
            type(hands) is not int or not 1<=hands<=game.hands or
            not isinstance(multipliers,(tuple,list)) or len(multipliers)!=game.hands or
            any(type(m) is not int or m not in game.possible_multipliers for m in multipliers)):
        raise StrategyError('Invalid round settings')
    if feature and (hands!=game.hands or base!=5):
        raise StrategyError('Feature advice requires the selected full board at max bet')
    return game.id,tuple(hand),feature,base,hands,sum(multipliers[:hands])


class GameStrategyTable:
    def __init__(self,game_id,directory=None):
        self.game=get_game(game_id)
        self.directory=Path(directory) if directory is not None else Path(__file__).with_name('strategy')
        path=self.directory/'cabinet'/(self.game.id+'.json')
        if path.is_symlink() or not path.is_file() or not 1<=path.stat().st_size<=100000:
            raise StrategyError('Missing bounded game strategy metadata')
        try:meta=json.loads(path.read_text())
        except (ValueError,OSError) as error:raise StrategyError('Unreadable strategy metadata') from error
        g=self.game
        if (meta.get('schema')!=2 or meta.get('game_id')!=g.id or meta.get('family')!=g.family or
                meta.get('num_hands')!=g.hands or meta.get('deck_size')!=g.deck_size or
                meta.get('category_order')!=list(g.categories) or meta.get('payouts')!=list(g.pays) or
                meta.get('multiplier_order')!=list(g.multipliers) or meta.get('low_coin')!=dict(g.low_coin)):
            raise StrategyError('Strategy does not match the selected game')
        name={'standard':'subset_counts.dat','deuces':'deuces_counts.dat','joker':'joker_counts.dat'}[g.family]
        counts=self.directory/name
        sections=[];offset=64;nc=len(g.categories)
        for k in range(5):
            width=4 if k<2 else 2 if k<4 else 1
            rows=CHOOSE[g.deck_size][k]
            sections.append({'subset_size':k,'offset':offset,'rows':rows,'width':width})
            offset+=rows*nc*width
        if (meta.get('counts_file')!=name or meta.get('sections')!=sections or
                meta.get('table_bytes')!=offset or counts.is_symlink() or not counts.is_file() or
                counts.stat().st_size!=offset):
            raise StrategyError('Invalid strategy count inventory')
        self.raw=counts.read_bytes()
        if (hashlib.sha256(self.raw).hexdigest()!=meta.get('table_sha256') or
                struct.unpack_from('<8s6I4Q',self.raw)!=(b'UXSUB01\0',1,64,nc,g.deck_size,4,0,64,offset-64,0,0)):
            raise StrategyError('Strategy count hash/header mismatch')
        reachable={0}
        for _ in range(g.hands):reachable={s+m for s in reachable for m in g.possible_multipliers}
        b=meta.get('bias',{});states=b.get('states');values=b.get('values');span=b.get('bellman_span')
        if (b.get('num_hands')!=g.hands or states!=sorted(reachable) or not isinstance(values,list) or
                len(values)!=len(reachable) or any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or
                type(span) not in (int,float) or not math.isfinite(span) or not 0<=span<=1e-6):
            raise StrategyError('Uncertified continuation values')
        self.bias=dict(zip(states,values));self.certificate=span
        self.sections=sections;self.index={c:i for i,c in enumerate(g.categories)};self.metadata=meta

    def counts(self,hand,cancel=None):
        g=self.game;nc=len(g.categories)
        if (len(hand)!=5 or len(set(hand))!=5 or
                any(type(c) is not int or not 0<=c<g.deck_size for c in hand)):
            raise StrategyError('Invalid dealt hand')
        rows=[]
        for mask in range(32):
            _check_cancel(cancel)
            held=sorted(c for i,c in enumerate(hand) if mask&(1<<i))
            k=len(held)
            if k==5:
                row=[0]*nc;row[self.index[evaluate_game_hand(hand,g)]]=1
            else:
                section=self.sections[k];width=section['width']
                rank=sum(CHOOSE[c][i+1] for i,c in enumerate(held))
                row=list(struct.unpack_from('<'+str(nc)+{1:'B',2:'H',4:'I'}[width],
                                            self.raw,section['offset']+rank*nc*width))
            rows.append(row)
        for bit in range(5):
            _check_cancel(cancel)
            for mask in range(32):
                if not mask&(1<<bit):rows[mask]=[a-b for a,b in zip(rows[mask],rows[mask|(1<<bit)])]
        for mask,row in enumerate(rows):
            if min(row)<0 or sum(row)!=CHOOSE[g.deck_size-5][5-mask.bit_count()]:
                raise StrategyError('Completion histogram failed validation')
        return rows

    def advise(self,frozen,cancel=None):
        hand,feature,base,hands,multiplier_sum=frozen
        g=self.game;rows=self.counts(hand,cancel)
        payouts=tuple(g.award(c,base) for c in g.categories)
        immediate=[];probabilities=[]
        for row in rows:
            denominator=sum(row)
            immediate.append(multiplier_sum*sum(n*p for n,p in zip(row,payouts))/denominator)
            q=Counter()
            for n,m in zip(row,g.multipliers):
                if n:q[m]+=n
            probabilities.append(tuple((m,n/denominator) for m,n in sorted(q.items())))
        scores=list(immediate);evaluated=32
        if feature:
            if hands!=g.hands or base!=5 or multiplier_sum not in self.bias:
                raise StrategyError('Invalid feature round')
            lo,hi=min(self.bias),max(self.bias)
            slope=(self.bias[hi]-self.bias[lo])/(hi-lo)
            residual=[v-slope*s for s,v in self.bias.items()]
            low,high=min(residual),max(residual)
            linear=[immediate[i]+slope*g.hands*sum(m*p for m,p in probabilities[i]) for i in range(32)]
            lower=max(linear)+low;scores=[-math.inf]*32;evaluated=0
            for mask in range(32):
                _check_cancel(cancel)
                if linear[mask]+high<lower-1e-9:continue
                distribution={0:1.0}
                for _ in range(g.hands):
                    _check_cancel(cancel)
                    next_distribution={}
                    for current,p in distribution.items():
                        for m,q in probabilities[mask]:
                            dest=current+m
                            next_distribution[dest]=next_distribution.get(dest,0.0)+p*q
                    distribution=next_distribution
                    time.sleep(0)
                scores[mask]=immediate[mask]+sum(p*self.bias[s] for s,p in distribution.items())
                lower=max(lower,scores[mask]);evaluated+=1
        _check_cancel(cancel)
        best=max(scores)
        mask=max((m for m,s in enumerate(scores) if best-s<=1e-9),key=lambda m:(m.bit_count(),-m))
        return {'mask':mask,'game_id':g.id,'expected_current_win':immediate[mask],'value':scores[mask],
                'feature':feature,'continuation_bellman_span':self.certificate if feature else 0.0,
                'evaluated_holds':evaluated}


class CabinetStrategyTable:
    def __init__(self,directory=None):
        self.directory=directory;self.table=None

    def advise(self,frozen,cancel=None):
        game_id=frozen[0]
        _check_cancel(cancel)
        if self.table is None or self.table.game.id!=game_id:
            self.table=GameStrategyTable(game_id,self.directory)
        _check_cancel(cancel)
        return self.table.advise(frozen[1:],cancel)


class CabinetAdvisor(StrategyAdvisor):
    _freeze_round=staticmethod(freeze_round)

    def __init__(self,directory=None,table_factory=CabinetStrategyTable):
        super().__init__(directory,table_factory)
