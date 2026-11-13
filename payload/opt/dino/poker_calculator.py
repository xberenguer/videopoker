"""Manual, offline card/multiplier entry using the cabinet's certified solver.

The calculator has no RNG, credits, wallet access, camera or network. UI state
is private RAM data. Changing an input cancels and invalidates old advice.
"""
import math
import time

from PIL import Image, ImageDraw
from poker_games import GAMES, get_game
from poker_cabinet_strategy import CabinetAdvisor, freeze_round
from poker_cabinet_ui import CabinetRenderer, FOOTERS

BG=(11,0,107)
PANEL=(21,23,63)
WHITE=(245,245,250)
MUTED=(158,165,192)
GOLD=(255,235,36)
RED=(246,77,83)
RANKS=('2','3','4','5','6','7','8','9','10','J','Q','K','A')
SUITS=('C','D','H','S')


def label(card):
    return 'JOKER' if card==52 else RANKS[card%13]+SUITS[card//13]


class CardCalculator:
    def __init__(self,renderer=None,advisor=None,clock=time.monotonic):
        self.renderer=renderer or CabinetRenderer()
        self._advisor=advisor
        self._clock=clock
        self._states={}
        self.game_id='ddb10'
        self.menu_index=9
        self.page='cabinet'
        self.focus=0
        self.selected_card=0
        self.picker_card=0
        self.picker_batch=False
        self.multiplier_focus=0
        self.result=None
        self.status='Enter five cards and the current multipliers.'
        self._token=None
        self._request_key=None
        self._closed=False
        self.exit_requested=False
        self.compare_ev_requested=False
        self.profile_resolver = lambda game_id: game_id

    @property
    def game(self):return get_game(self.game_id)

    @property
    def state(self):
        if self.game_id not in self._states:
            self._states[self.game_id]={'cards':[None]*5,'multipliers':[1]*self.game.hands,'continued':True}
        return self._states[self.game_id]

    @property
    def cards(self):return self.state['cards']

    @property
    def multipliers(self):return self.state['multipliers']

    def open(self,game_id=None):
        if game_id is not None:self.menu_index=next(i for i,g in enumerate(GAMES) if g.id==get_game(game_id).cabinet_id)
        self.cancel()
        self.page='cabinet'
        self.exit_requested=False

    def select_game(self,game_id):
        game=get_game(self.profile_resolver(game_id))
        self.cancel()
        self.game_id=game.id
        self.menu_index=next(i for i,g in enumerate(GAMES) if g.id==game.cabinet_id)
        self.page='editor'
        self.focus=self.selected_card=0
        self.status='Enter five cards and the current multipliers.'
        if None not in self.cards:self.calculate()

    def cancel(self):
        if self._advisor is not None:self._advisor.cancel()
        self._token=self._request_key=None
        self.result=None
        self.compare_ev_requested=False

    def changed(self):
        self.cancel()
        self.status='Ready to calculate.' if None not in self.cards else 'Choose all five cards.'
        if None not in self.cards:
            self.calculate()

    def set_card(self,index,card):
        if type(index) is not int or not 0<=index<5:raise ValueError('Invalid card slot')
        if card is not None and (type(card) is not int or not 0<=card<self.game.deck_size):
            raise ValueError('Card outside this game deck')
        if card is not None and any(c==card for i,c in enumerate(self.cards) if i!=index):
            raise ValueError('This card is already selected')
        self.cards[index]=card
        self.changed()

    def set_multiplier(self,index,value):
        if type(index) is not int or not 0<=index<self.game.hands:raise ValueError('Invalid hand slot')
        if type(value) is not int or value not in self.game.possible_multipliers:
            raise ValueError('Multiplier outside this game schedule')
        self.multipliers[index]=value
        self.changed()

    def set_continued(self,value):
        if type(value) is not bool:raise ValueError('Invalid strategy mode')
        self.state['continued']=value
        self.changed()

    def snapshot(self):
        return {'game_id':self.game.id,'phase':'hold','initial':list(self.cards),
                'round_feature':self.state['continued'],'round_base_bet':5,
                'round_num_hands':self.game.hands,'active_multipliers':list(self.multipliers)}

    def calculate(self):
        if None in self.cards:
            self.status='Choose all five cards first.'
            return False
        snapshot=self.snapshot()
        key=freeze_round(snapshot)
        if self._advisor is None:self._advisor=CabinetAdvisor()
        self.result=None
        self._token=self._advisor.request(snapshot)
        self._request_key=key
        self.status='Calculating all 32 holds...'
        return True

    def update(self,now):
        if self._closed or self._token is None:return False
        answer=self._advisor.poll(self._token)
        if answer is None:return False
        current=freeze_round(self.snapshot())
        if current!=self._request_key:
            self.cancel();return True
        self._token=None
        if answer.get('error'):
            self.result=None;self.status='Calculation failed. Top button: retry.'
        else:
            if (type(answer.get('mask')) is not int or not 0<=answer['mask']<=31 or
                    answer.get('game_id')!=self.game.id):
                self.result=None;self.status='Invalid solver response. Please retry.'
            else:
                self.result=dict(answer)
                self.status=self.hold_text()
        return True

    def hold_text(self):
        if self.result is None:return self.status
        positions=[str(i+1) for i in range(5) if self.result['mask']&(1<<i)]
        if not positions:return 'HOLD NONE - DRAW ALL FIVE'
        if len(positions)==5:return 'HOLD ALL FIVE CARDS'
        return 'HOLD '+', '.join(positions)

    def ev_values(self):
        if self.result is None:return None
        total=self.result.get('value');current=self.result.get('expected_current_win')
        if not all(type(n) in (int,float) and math.isfinite(n) for n in (total,current)):return None
        future=total-current
        if abs(future)<1e-9:future=0.
        return total,current,future

    def start_picker(self,index):
        self.selected_card=index
        self.picker_batch=self.cards[index] is None
        self.picker_card=self.cards[index] if self.cards[index] is not None else self.picker_card
        if self.picker_card>=self.game.deck_size:self.picker_card=0
        self.page='picker'
        self.status='Middle button: choose this card.'

    def choose_card(self):
        try:self.set_card(self.selected_card,self.picker_card)
        except ValueError:
            self.status='Already used. Choose a different card.'
            return
        if self.picker_batch and None in self.cards:
            self.selected_card=next((self.selected_card+n)%5 for n in range(1,6) if self.cards[(self.selected_card+n)%5] is None)
            self.status='Middle button: choose the next card.'
        else:
            self.page='editor'
            self.focus=self.selected_card

    def multiplier_positions(self):
        if self.game.hands==10:
            points={0:(160,185)}
            for row,ids in enumerate(((7,8,9),(4,5,6),(1,2,3))):
                points.update({i:(60+100*col,56+43*row) for col,i in enumerate(ids)})
        elif self.game.hands==5:
            points={3:(85,62),4:(235,62),1:(85,111),2:(235,111),0:(160,162)}
        else:points={2:(160,58),1:(160,105),0:(160,152)}
        points[self.game.hands]=(48,200)  # ALL selector, not an extra hand.
        return points

    def move_multiplier(self,action):
        points=self.multiplier_positions();x,y=points[self.multiplier_focus]
        dx,dy={'UP':(0,-1),'DOWN':(0,1),'LEFT':(-1,0),'RIGHT':(1,0)}[action]
        candidates=[]
        for index,(xx,yy) in points.items():
            forward=(xx-x)*dx+(yy-y)*dy
            if forward>0:
                side=abs((xx-x)*dy-(yy-y)*dx)
                candidates.append((forward+side*2,side,index))
        if candidates:self.multiplier_focus=min(candidates)[2]

    def change_multiplier(self,direction):
        values=self.game.possible_multipliers
        index=self.multiplier_focus
        current=self.multipliers[index] if index<self.game.hands else (self.multipliers[0] if len(set(self.multipliers))==1 else 1)
        target=1 if index==self.game.hands and len(set(self.multipliers))>1 else values[(values.index(current)+direction)%len(values)]
        if index==self.game.hands:
            self.multipliers[:]=[target]*self.game.hands
            self.changed()
        else:self.set_multiplier(index,target)

    def handle(self,action):
        if self._closed:return
        if action not in ('UP','DOWN','LEFT','RIGHT','CENTER','KEY1','KEY2','KEY3'):raise ValueError('Unknown action')
        confirm=action in ('CENTER','KEY2')
        if self.page=='pays':
            if confirm or action in ('KEY1','KEY3'):self.page='editor'
            return
        if self.page=='cabinet':
            if action=='KEY3':self.cancel();self.exit_requested=True
            elif action in ('LEFT','RIGHT'):self.menu_index=(self.menu_index+(-1 if action=='LEFT' else 1))%12
            elif action in ('UP','DOWN'):self.menu_index=(self.menu_index+(-4 if action=='UP' else 4))%12
            elif confirm or action=='KEY1':self.select_game(GAMES[self.menu_index].id)
            return
        if self.page=='picker':
            if action=='KEY3':self.page='editor';return
            if action=='KEY1':self.set_card(self.selected_card,None);self.page='editor';return
            if confirm:self.choose_card();return
            rank=self.picker_card%13 if self.picker_card<52 else 0
            suit=self.picker_card//13
            if action in ('LEFT','RIGHT') and suit<4:rank=(rank+(-1 if action=='LEFT' else 1))%13
            elif action in ('UP','DOWN'):suit=(suit+(-1 if action=='UP' else 1))%(5 if self.game.deck_size==53 else 4)
            self.picker_card=52 if suit==4 else suit*13+rank
            self.status='Already used.' if self.picker_card in [c for i,c in enumerate(self.cards) if i!=self.selected_card] else 'Middle button: choose this card.'
            return
        if self.page=='multipliers':
            if action=='KEY3':self.page='editor';return
            if action=='KEY1':self.change_multiplier(-1)
            elif confirm:self.change_multiplier(1)
            else:self.move_multiplier(action)
            return
        if action=='KEY3':self.cancel();self.page='cabinet';return
        if action=='KEY1':self.calculate();return
        if confirm:
            if self.focus<5:self.start_picker(self.focus)
            elif self.focus==5:
                self.page='multipliers'
                self.multiplier_focus={3:2,5:3,10:7}[self.game.hands]
            elif self.focus==6:self.set_continued(not self.state['continued'])
            elif self.focus==7:self.calculate()
            elif self.focus==8:
                if None in self.cards:self.status='Choose all five cards first.'
                else:self.compare_ev_requested=True
            elif self.focus==9:self.page='pays'
            else:self.cards[:]=[None]*5;self.changed();self.focus=0
            return
        rows=((0,1,2,3,4),(5,6),(7,8,9,10))
        row=0 if self.focus<5 else 1 if self.focus<7 else 2
        if action in ('LEFT','RIGHT'):
            indices=rows[row];self.focus=indices[(indices.index(self.focus)+(-1 if action=='LEFT' else 1))%len(indices)]
        elif action in ('UP','DOWN'):
            target=(row+(-1 if action=='UP' else 1))%3
            centers=(48,104,160,216,272,88,241,57,157,233,287)
            self.focus=min(rows[target],key=lambda i:abs(centers[i]-centers[self.focus]))
        if self.focus<5:self.selected_card=self.focus

    def text(self,image,xy,text,size=11,color=WHITE,bold=False):
        self.renderer.text(ImageDraw.Draw(image),xy,text,size,color,bold)

    def center(self,image,x,y,text,size=11,color=WHITE,bold=False):
        self.renderer.center(ImageDraw.Draw(image),x,y,text,size,color,bold)

    def button(self,image,box,text,selected=False,size=11):
        d=ImageDraw.Draw(image)
        d.rounded_rectangle(box,radius=4,fill=(52,54,106) if selected else PANEL,
                            outline=GOLD if selected else (83,86,129),width=2 if selected else 1)
        self.renderer.fitted_label(image,(box[0]+3,box[1]+2,box[2]-3,box[3]-2),text,size,GOLD if selected else WHITE,True)

    def header(self,image,title,subtitle):
        ImageDraw.Draw(image).rectangle((0,0,319,27),fill=(3,3,40))
        self.text(image,(9,3),title,12,GOLD,True)
        self.text(image,(9,18),subtitle,8,MUTED)

    def render(self):
        image=Image.new('RGB',(320,240),BG)
        game=self.game
        if self.page=='cabinet':
            self.renderer.render_menu(image,{'game_id':game.id},{'page':'cabinet','index':self.menu_index,'return':False})
            self.header(image,'CARD CALCULATOR','Select the game and its matching paytable')
            self.center(image,160,223,'MIDDLE: SELECT    BOTTOM: BACK TO PLAY',8,WHITE)
            return image
        full=game.pays[game.categories.index('full_house')]
        flush=game.pays[game.categories.index('flush')]
        title=FOOTERS[game.id]+' '+str(full)+'/'+str(flush)+' - '+str(game.hands)+' PLAY'
        self.header(image,title,'CARD CALCULATOR - MAX BET')
        if self.page=='pays':
            source=self.renderer.render_paytable_source({'game_id':game.id},{'bet':5})
            image=source.resize((320,240),Image.Resampling.LANCZOS)
            ImageDraw.Draw(image).rectangle((0,219,319,239),fill=(0,0,0))
            self.center(image,160,226,'MIDDLE / BOTTOM: BACK TO CALCULATOR',8,WHITE)
            return image
        if self.page=='picker':
            self.header(image,'CHOOSE CARD '+str(self.selected_card+1),'Left/right: rank    Up/down: suit')
            used={c for i,c in enumerate(self.cards) if i!=self.selected_card and c is not None}
            d=ImageDraw.Draw(image)
            for suit in range(4):
                yy=46+36*suit
                color=RED if suit in (1,2) else WHITE
                self.text(image,(6,yy+8),SUITS[suit],11,color,True)
                for rank in range(13):
                    card=suit*13+rank;xx=25+22*rank
                    chosen=card==self.picker_card
                    box=(xx,yy,xx+20,yy+29)
                    d.rounded_rectangle(box,radius=2,fill=(71,69,32) if chosen else PANEL,
                                        outline=GOLD if chosen else (55,55,100),width=2 if chosen else 1)
                    self.renderer.fitted_label(image,(xx+2,yy+4,xx+18,yy+23),RANKS[rank],13,
                                                (80,81,115) if card in used else color,True)
                    if card in used:d.line((xx+3,yy+24,xx+17,yy+6),fill=(112,104,117),width=1)
            if game.deck_size==53:
                self.button(image,(25,193,111,213),'JOKER',self.picker_card==52,11)
            self.text(image,(129,195),'SELECTED: '+label(self.picker_card),10,GOLD,True)
            self.center(image,160,219,'ALREADY USED' if self.picker_card in used else 'MIDDLE: CHOOSE   TOP: CLEAR   BOTTOM: BACK',8,RED if self.picker_card in used else WHITE)
            return image
        if self.page=='multipliers':
            self.header(image,'CURRENT MULTIPLIERS',str(game.hands)+' hands - same positions as the game')
            for i,(x,y) in self.multiplier_positions().items():
                if i==game.hands:
                    values=set(self.multipliers)
                    title='ALL '+(str(next(iter(values)))+'x' if len(values)==1 else 'MIXED')
                    self.button(image,(x-40,y-12,x+40,y+12),title,self.multiplier_focus==i,10)
                else:
                    self.button(image,(x-41,y-15,x+41,y+15),str(self.multipliers[i])+'x',self.multiplier_focus==i,17)
                    if i==0:self.center(image,x,y+17,'BOTTOM HAND',7,MUTED)
            self.text(image,(214,200),'TOTAL '+str(sum(self.multipliers))+'x',9,GOLD,True)
            self.center(image,160,225,'MIDDLE: +   TOP: -   D-PAD: MOVE   BOTTOM: BACK',8,WHITE)
            return image
        self.renderer._game=game
        for i,card in enumerate(self.cards):
            x=22+56*i
            held=self.result is not None and bool(self.result['mask']&(1<<i))
            face=self.renderer.card(card,52,75)
            image.paste(face,(x,36),face)
            d=ImageDraw.Draw(image)
            if self.focus==i:d.rounded_rectangle((x-3,32,x+54,114),radius=4,outline=WHITE,width=2)
            if held:
                d.rounded_rectangle((x-2,33,x+53,113),radius=4,outline=GOLD,width=2)
                self.renderer.paste(image,'gui/hold.png',(x+10,105),(32,13))
            self.center(image,x+26,28,str(i+1),8,MUTED)
            if card is None:self.center(image,x+26,115,'CHOOSE',8,GOLD)
        line=self.hold_text() if self.result is not None else self.status
        ev=self.ev_values()
        self.renderer.fitted_label(image,(10,120 if ev else 126,310,135 if ev else 141),line,12,GOLD if self.result is not None else WHITE,True)
        if ev is not None:
            for box,value,color in (((10,136,115,148),'EV %.3f cr'%ev[0],GOLD),
                                    ((117,136,210,148),'NOW %.3f'%ev[1],WHITE),
                                    ((212,136,310,148),'NEXT %.3f'%ev[2],WHITE)):
                self.renderer.fitted_label(image,box,value,8,color,True)
        self.button(image,(10,151,166,181),'MULTIPLIERS '+str(sum(self.multipliers))+'x',self.focus==5,10)
        self.button(image,(173,151,310,181),'CONTINUED PLAY' if self.state['continued'] else 'THIS HAND ONLY',self.focus==6,10)
        self.button(image,(10,191,104,217),'CALCULATE' if self._token is None else 'WORKING...',self.focus==7,10)
        self.button(image,(110,191,204,217),'COMPARE EV',self.focus==8,10)
        self.button(image,(210,191,257,217),'PAYS',self.focus==9,9)
        self.button(image,(263,191,310,217),'CLEAR',self.focus==10,9)
        self.center(image,160,227,'TOP: CALCULATE    MIDDLE: SELECT    BOTTOM: GAMES',8,MUTED)
        return image

    def close(self):
        if self._closed:return
        if self._advisor is not None:self._advisor.close()
        self._closed=True
