"""Reference cabinet menu, per-game bank, and 3/5/10-hand bitmap layouts."""
import math
from PIL import Image, ImageDraw
from poker_engine import Session
from poker_games import GAMES, get_game
from poker_ui import Renderer, WIDTH, HEIGHT, GOLD, WHITE, _short_number

LAYOUTS={
    3:((103,262,433,120),(103,131,433,120),(103,2,433,120)),
    5:((108,268,433,120),(85,131,204,120),(385,131,204,120),
       (85,2,204,120),(385,2,204,120)),
    10:Renderer.HANDS,
}
FOOTERS={'bp3':'Bonus Poker','bpd3':'Bonus Poker Dlx','ddb3':'Double Dbl Bonus',
         'dw3':'Deuces Wild','job5':'Jacks or Better','db5':'Double Bonus',
         'joker5':'Joker Poker','dw5':'Deuces Wild','bp10':'Bonus Poker',
         'ddb10':'Double Dbl Bonus','tdb10':'Triple Double Bonus','dwb10':'Deuces Wild Bonus'}
WIN_ROWS={9:(3,9,10,11,12,13,14,15,16),
          10:(1,3,2,4,9,10,11,12,13,14),
          11:(3,9,6,5,10,11,12,13,14,15,16),
          13:(3,9,4,2,2,5,10,11,12,13,14,15,16)}


class GameBank:
    """RAM-only shared credits and game-specific pending multipliers.

    Tile selection resets the cards and selects the user's preferred maximum
    wager and full board. Earned multipliers survive returning to that game.
    Merely returning from More Games leaves the current game unchanged.
    """
    def __init__(self):
        self.pending={}
        self.active_id=None

    def select(self,game_id,current):
        game=get_game(game_id)
        if current.phase=='hold':raise ValueError('Finish the hand before changing games')
        self.pending[current.game.id]=tuple(current.multipliers)
        session=Session(credits=current.credits,rng=current._rng,game_id=game.id)
        if game.id in self.pending:session.multipliers=list(self.pending[game.id])
        self.active_id=game.id
        return session


class CabinetRenderer(Renderer):
    @staticmethod
    def game(snapshot):return get_game(snapshot.get('game_id','ddb10'))

    def card(self,card,width,height,held=False,selected=False,mini=False,disabled=False):
        game=getattr(self,'_game',get_game('ddb10'))
        if card==52:
            if game.family!='joker':raise ValueError('Joker outside Joker Poker')
            return self.sprite('cards/Joker.png',(width,height))
        if card is not None and game.family=='deuces' and card%13==0:
            return self.sprite('cards/'+str(self.source_card(card))+'w.png',(width,height))
        return super().card(card,width,height,held,selected,mini,disabled)

    def _mult_art(self,image,number,left,top,height,opacity):
        name='multipliers/'+str(number)+'x_2.png'
        asset=self.assets[name];width=round(asset.width*height/asset.height)
        self.paste(image,name,(left-width,top),(width,height),opacity)

    def multiplier(self,image,index,current,following,opacity=1.0):
        x,y,width,height=self.HANDS[index]
        small=16 if self._game.hands==10 else 20
        if following>1:
            self.paste(image,'multipliers/nexthand.png',(x-(66 if small==16 else 86),y+2),
                       (25,16) if small==16 else (32,20),opacity)
            self._mult_art(image,following,x-3,y+2,small,opacity)
        if current>1:
            large=round(small*1.5)
            self._mult_art(image,current,x-3,y+height-large-5,large,opacity)

    def display_category(self,category):
        game=self._game
        if category in game.rows:return category
        if category.startswith('four_'):
            if category=='four_deuces_ace' and 'four_deuces' in game.rows:return 'four_deuces'
            if 'four_aces' in category and 'four_aces' in game.rows:return 'four_aces'
            if 'four_234' in category and 'four_234' in game.rows:return 'four_234'
            return 'four_5k'
        if category.startswith('five_'):return 'five_6k'
        return category

    def win_indicator(self,image,index,result):
        category=self.display_category(result.get('category','nothing'))
        if not result.get('payout') or category not in self._game.rows:return
        row=self._game.rows.index(category)
        art=WIN_ROWS[len(self._game.rows)][row]
        x,y,width,height=self.HANDS[index];cx,cy=x+width/2,y+.65*height
        self.paste(image,'wins/payline'+str(art)+'.png',(cx-65,cy-14),(130,35))
        draw=ImageDraw.Draw(image)
        label=self._game.label(category).title()
        if category=='four_5k' and len(self._game.rows)!=9:label='4 5s thru Ks' if self._game.family=='standard' else '4 of a Kind'
        self.canvas_text(draw,cx,cy-4-11*.99/2,label,11,WHITE,align='center')
        amount=str(result['payout'])
        if result.get('multiplier',1)>1:amount='%s X %s = %s'%(result['multiplier'],result['base_payout'],result['payout'])
        self.canvas_text(draw,cx,cy+9-10*.99/2,amount,10,GOLD,True,'center')

    def _render_board(self,snapshot,selected_card=0,selected_hand=0):
        self._game=self.game(snapshot);self.HANDS=LAYOUTS[self._game.hands]
        image=self.background.copy();draw=ImageDraw.Draw(image)
        phase=snapshot['phase'];initial=snapshot.get('initial') or [];held=snapshot['held']
        hands,results=snapshot['hands'],snapshot['results']
        next_x,current_x=snapshot['multipliers'],snapshot['active_multipliers']
        reveal,deal_reveal=int(snapshot.get('_reveal',5)),int(snapshot.get('_deal_reveal',5))
        active=snapshot['round_num_hands'] if phase in ('hold','result') else snapshot['num_hands']
        for index,(x,y,width,height) in enumerate(self.HANDS):
            enabled=index<active
            if phase=='result' and index<len(hands):
                cards=[c if n<reveal or held[n] else None for n,c in enumerate(hands[index])]
            elif phase=='hold' and len(initial)==5 and enabled:
                cards=[c if (n<deal_reveal if index==0 else held[n]) else None for n,c in enumerate(initial)]
            else:cards=[None]*5
            size,step=(((56,80),20) if self._game.hands==10 else ((83,119),30)) if index else ((83,119),87)
            if self._game.hands==3:size,step=(83,119),87
            for n,card in enumerate(cards):
                asset=self.card(card,*size,disabled=not enabled);image.paste(asset,(x+n*step,y),asset)
            following=next_x[index] if phase=='ready' or (phase=='result' and reveal==5) else 1
            current=current_x[index] if phase!='ready' and enabled else 1
            self.multiplier(image,index,current,following,1 if enabled else .6)
            if enabled and phase=='result' and reveal==5:self.win_indicator(image,index,results[index])
        base_left=self.HANDS[0][0]
        for n,is_held in enumerate(held):
            if is_held and phase in ('hold','result'):self.paste(image,'gui/hold.png',(base_left+41+87*n-24,375))
        total=snapshot['total_win'] if phase=='result' else 0
        if total:self.canvas_text(draw,106,410,_short_number(total),15,GOLD,True,'right')
        for x,y,value,size,align in ((167,410,snapshot['total_bet'],15,'right'),
                (630,412,snapshot['credits'],16,'right'),(322,422,snapshot['num_hands'],15,'center'),
                (413,422,snapshot['bet_per_hand'],15,'center')):
            self.canvas_text(draw,x,y,_short_number(value),size,GOLD,True,align)
        self.paste(image,'gui/speaker_3.png',(457,405))
        insufficient=snapshot['credits']<snapshot['total_bet']
        names=('SeePaysHelp','MoreGames','Speed%02d'%(int(snapshot.get('_speed',1))+1),
               'SelectHands','BetPerHand','BetMax','Draw' if phase=='hold' else 'Deal')
        for i,name in enumerate(names):
            disabled=(i in (3,4) or (phase=='hold' and i in (1,5))
                      or (i==5 and (insufficient or snapshot['credits']<=0)) or (i==6 and phase!='hold' and insufficient))
            if disabled:name='SpeedDim' if i==2 else name+'Dim'
            self.paste(image,'gui/'+name+'.png',(self.BUTTON_X[i],437),(86,30))
        self.canvas_text(draw,318,466,FOOTERS[self._game.id],11,WHITE,align='center')
        if (phase=='result' and reveal==5) or snapshot.get('_cabinet_game_over'):
            self.canvas_text(draw,15,467,'Game Over',10,WHITE)
        return image

    def render_paytable_source(self,snapshot,menu):
        game=self.game(snapshot);image=self.assets['backgrounds/uxpaytablebg.png'].convert('RGB');draw=ImageDraw.Draw(image)
        bet=menu.get('bet',1)
        if bet not in (1,2,3,4,5,10):bet=1
        for n,(left,width) in enumerate(((225,74),(297,74),(369,74),(441,74),(514,122)),1):
            draw.rectangle((left+2,1,left+width-5,188),fill=(176,0,0) if n==min(bet,5) else (0,1,68))
        draw.rectangle((374,198,490,385),fill=(176,0,0) if bet==10 else (0,1,68))
        size=round(170/len(game.rows),6);step=size+size/13
        for row,category in enumerate(game.rows):
            label=game.label(category);bold=self._text_run(label,size,True)[1]<=214
            length=self._text_run(label,size,bold)[1]
            dots=max(0,math.ceil((219-length)/self._text_run('.',size,True)[1])-1)
            label+='.'*dots
            self.canvas_text(draw,6.5,2.3+row*step,label,size,GOLD,bold)
            self.canvas_text(draw,149.5,199+row*step,label,size,GOLD,bold)
            for coin,right in enumerate((291,363,435,507,631),1):
                self.canvas_text(draw,right,2.3+row*step,game.award(category,coin),size,GOLD,True,'right')
            self.canvas_text(draw,487,199+row*step,str(game.multiplier(category))+'X',size,GOLD,True,'right')
        self.canvas_text(draw,314,410,'BET',19,WHITE,True);self.canvas_text(draw,357,410,bet,19,WHITE,True)
        self.paste(image,'help/buttons/help.png',(1,440))
        if bet>1:self.paste(image,'help/buttons/betdown.png',(341,440))
        if bet<10:self.paste(image,'help/buttons/betup.png',(440,440))
        self.paste(image,'help/buttons/return.png',(548,440))
        return image

    def render_menu(self,image,snapshot,menu):
        if menu.get('page')!='cabinet':
            self._game=self.game(snapshot)
            return super().render_menu(image,snapshot,menu)
        source=self.assets['backgrounds/uxbg.png'].convert('RGB');draw=ImageDraw.Draw(source)
        selected=int(menu.get('index',0))%12
        for index,game in enumerate(GAMES):
            x,y=30+157*(index%4),74+100*(index//4)
            if index==selected:self.paste(source,'cabinet/selection.png',(x-8,y-8),(148,91))
            self.paste(source,'cabinet/'+game.id+'.png',(x,y),(130,66))
            self.canvas_text(draw,x+65,y+67,'Poker',11,WHITE,True,'center')
        if menu.get('return'):self.paste(source,'cabinet/return.png',(545,430),(83,49))
        image.paste(source.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS))
