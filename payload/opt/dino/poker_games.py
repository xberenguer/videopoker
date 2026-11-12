"""Cabinet game definitions transcribed from the twelve reference pay screens.

No executable vendor code. All awards are play credits. The category vectors
retain distinctions required by other paytables, even when a game merges them.
"""
from dataclasses import dataclass

STANDARD_CATEGORIES = (
    'royal_flush', 'straight_flush', 'four_aces_kicker', 'four_234_kicker',
    'four_aces', 'four_234', 'four_5k', 'full_house', 'flush', 'straight',
    'three_kind', 'two_pair', 'high_pair', 'nothing',
)
WILD_CATEGORIES = STANDARD_CATEGORIES + (
    'wild_royal', 'four_deuces', 'four_deuces_ace',
    'five_aces', 'five_345', 'five_6k',
)
LABELS = {
    'royal_flush':'ROYAL FLUSH', 'straight_flush':'STRAIGHT FLUSH',
    'four_aces_kicker':'4 ACES W/ 2,3,4',
    'four_234_kicker':'4 2S,3S,4S W/ ACE 2,3,4',
    'four_aces':'4 ACES', 'four_234':'4 2S,3S,4S', 'four_5k':'4 5S THRU KS',
    'full_house':'FULL HOUSE','flush':'FLUSH','straight':'STRAIGHT',
    'three_kind':'3 OF A KIND','two_pair':'2 PAIR','high_pair':'JACKS OR BETTER',
    'nothing':'NO WIN','wild_royal':'ROYAL FLUSH W/ DEUCES',
    'four_deuces':'4 DEUCES','four_deuces_ace':'4 DEUCES PLUS ACE',
    'five_aces':'5 ACES','five_345':'5 3S 4S 5S','five_6k':'5 6S THRU KS',
}


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    hands: int
    family: str
    pays: tuple
    multipliers: tuple
    rows: tuple
    # Exceptional base 1..4 per-coin awards, before the max-coin jackpot.
    low_coin: tuple = (('royal_flush',250),)

    @property
    def categories(self):
        return STANDARD_CATEGORIES if self.family=='standard' else WILD_CATEGORIES

    @property
    def deck_size(self):
        return 53 if self.family=='joker' else 52

    def award(self, category, base):
        if type(base) is not int or not 1 <= base <= 5:
            raise ValueError('Invalid base wager')
        per_coin=self.pays[self.categories.index(category)]
        if base<5:
            per_coin=dict(self.low_coin).get(category,per_coin)
        return base*per_coin

    def multiplier(self, category):
        return self.multipliers[self.categories.index(category)]

    @property
    def possible_multipliers(self):
        return tuple(sorted(set(self.multipliers)))

    def label(self,key):
        if key=='royal_flush' and self.family!='standard':
            return 'ROYAL FLUSH NO WILD' if self.family=='joker' else 'ROYAL FLUSH NO DEUCES'
        if key=='four_5k' and self.id in ('bpd3','job5','joker5','dw3','dw5','dwb10'):
            return '4 OF A KIND'
        if key=='five_6k' and self.id in ('dw3','dw5','joker5'):
            return '5 OF A KIND'
        if key=='wild_royal' and self.family=='joker':return 'ROYAL FLUSH'
        if key=='high_pair' and self.family=='joker':return 'KINGS OR BETTER'
        return LABELS[key]


BONUS_ROWS=('royal_flush','straight_flush','four_aces','four_234','four_5k',
            'full_house','flush','straight','three_kind','two_pair','high_pair')
BASIC_ROWS=('royal_flush','straight_flush','four_5k','full_house','flush',
            'straight','three_kind','two_pair','high_pair')
DDB_ROWS=STANDARD_CATEGORIES[:-1]
DEUCES_ROWS=('royal_flush','four_deuces','wild_royal','five_6k','straight_flush',
             'four_5k','full_house','flush','straight','three_kind')
JOKER_ROWS=('royal_flush','five_6k','wild_royal','straight_flush','four_5k',
            'full_house','flush','straight','three_kind','two_pair','high_pair')
DWB_ROWS=('royal_flush','four_deuces_ace','four_deuces','wild_royal','five_aces',
          'five_345','five_6k','straight_flush','four_5k','full_house','flush',
          'straight','three_kind')
TDB_ROWS=('royal_flush','four_aces_kicker','four_234_kicker','four_aces','four_234',
          'four_5k','straight_flush','full_house','flush','straight','three_kind',
          'two_pair','high_pair')
BP=(800,50,80,40,80,40,25,7,5,4,3,2,1,0)
DDB=(800,50,400,160,160,80,50,9,6,4,3,1,1,0)
DW=(800,9,0,0,0,0,4,4,3,2,1,0,0,0,25,200,200,15,15,15)
GAMES=(
    Game('bp3','Bonus Poker',3,'standard',BP,
         (2,2,2,2,2,2,2,12,11,8,4,3,2,1),BONUS_ROWS),
    Game('bpd3','Bonus Poker Deluxe',3,'standard',
         (800,50,80,80,80,80,80,8,6,4,3,1,1,0),
         (2,2,2,2,2,2,2,12,11,7,4,3,2,1),BASIC_ROWS),
    Game('ddb3','Double Double Bonus',3,'standard',DDB,
         (2,2,2,2,2,2,2,12,10,8,4,3,2,1),DDB_ROWS),
    Game('dw3','Deuces Wild',3,'deuces',DW,
         (2,12,1,1,1,1,7,5,5,3,2,1,1,1,2,2,2,2,2,2),DEUCES_ROWS),
    Game('job5','Jacks or Better',5,'standard',
         (800,50,25,25,25,25,25,8,6,4,3,2,1,0),
         (2,2,3,3,3,3,3,12,11,7,4,3,2,1),BASIC_ROWS),
    Game('db5','Double Bonus',5,'standard',
         (800,50,160,80,160,80,50,9,6,4,3,1,1,0),
         (2,2,2,2,2,2,3,12,10,8,4,3,2,1),BONUS_ROWS),
    Game('joker5','Joker Poker',5,'joker',
         (800,50,0,0,0,0,15,7,5,3,2,1,1,0,100,0,0,200,200,200),
         (3,3,1,1,1,1,2,7,6,5,4,3,2,1,3,1,1,3,3,3),JOKER_ROWS),
    Game('dw5','Deuces Wild',5,'deuces',DW,
         (2,12,1,1,1,1,7,5,5,3,2,1,1,1,2,2,2,3,3,3),DEUCES_ROWS),
    Game('bp10','Bonus Poker',10,'standard',BP,
         (4,4,4,4,4,4,3,12,11,8,4,3,2,1),BONUS_ROWS),
    Game('ddb10','Double Double Bonus',10,'standard',DDB,
         (4,4,4,4,4,4,3,12,10,8,4,3,2,1),DDB_ROWS),
    Game('tdb10','Triple Double Bonus',10,'standard',
         (800,50,800,400,160,80,50,9,6,4,2,1,1,0),
         (2,2,2,2,2,2,2,12,10,8,4,3,2,1),TDB_ROWS,
         (('royal_flush',400),('four_aces_kicker',400))),
    Game('dwb10','Deuces Bonus Poker',10,'deuces',
         (800,9,0,0,0,0,4,4,3,1,1,0,0,0,25,200,400,80,40,20),
         (4,12,1,1,1,1,7,6,4,3,2,1,1,1,4,4,4,4,4,4),DWB_ROWS),
)
BY_ID={g.id:g for g in GAMES}


def get_game(game_id='ddb10'):
    try:return BY_ID[game_id]
    except (KeyError,TypeError) as error:raise ValueError('Unknown cabinet game') from error
