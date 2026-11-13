"""Game-first training layout: original-size cards, original footer, live sidebar.

Only the unused horizontal gaps between hands are tightened. No card faces or
machine controls are shrunk to make room for the 64-pixel information rail.
"""
import math
from PIL import Image,ImageDraw
from poker_cabinet_ui import CabinetRenderer
from poker_cabinet_strategy import freeze_round
from poker_games import get_game
from poker_training import TOLERANCE,autoplay_stats
from poker_ui import GOLD,WHITE,Renderer

GREEN=(71,238,151)
RED=(255,91,108)
MUTED=(157,170,199)
BG=(5,8,35)

LAYOUTS={
    3:((44,268,433,120),(44,134,433,120),(44,0,433,120)),
    5:((44,268,433,120),(48,132,204,120),(300,132,204,120),(48,0,204,120),(300,0,204,120)),
    10:((44,268,433,120),)+tuple((32+170*c,176-88*r,137,80) for r in range(3) for c in range(3)),
}


def positions(mask):
    return ','.join(str(i+1) for i in range(5) if mask&(1<<i)) or 'NONE'


class TrainingHUD:
    def __init__(self):
        self._key=None
        self._board=None
        self._fallback=None
        self.tab=0
        self._source=self._deal=None
        self._sidebar_key=self._sidebar_image=None

    def renderer(self,play):
        if isinstance(play.renderer,CabinetRenderer):return play.renderer
        if self._fallback is None:self._fallback=CabinetRenderer()
        return self._fallback

    def board(self,snapshot,renderer):
        keys=('game_id','phase','initial','held','hands','results','multipliers','active_multipliers',
              'round_num_hands','num_hands','_reveal','_deal_reveal')
        key=Renderer._freeze({k:snapshot.get(k) for k in keys})
        if key==self._key:return self._board
        deal=Renderer.deal_layer_key(snapshot)
        if deal is not None and self._deal is not None and deal[0]==self._deal[0] and deal[1]>=self._deal[1]:
            renderer.patch_deal_cards(self._source,self._board,snapshot,self._deal[1],deal[1],44,268)
            self._deal,self._key=deal,key
            return self._board
        game=get_game(snapshot['game_id']);layout=LAYOUTS[game.hands]
        image=renderer.background.copy()
        old_layout=renderer.HANDS
        renderer.HANDS=layout;renderer._game=game
        phase=snapshot['phase'];held=snapshot['held'];initial=snapshot['initial']
        reveal=snapshot.get('_reveal',5);deal_reveal=snapshot.get('_deal_reveal',5)
        try:
            for index,(x,y,width,height) in enumerate(layout):
                enabled=index<(snapshot['round_num_hands'] if phase in ('hold','result') else snapshot['num_hands'])
                if phase=='result' and index<len(snapshot['hands']):
                    cards=[c if i<reveal or held[i] else None for i,c in enumerate(snapshot['hands'][index])]
                elif phase=='hold' and len(initial)==5 and enabled:
                    cards=[c if (i<deal_reveal if index==0 else held[i]) else None for i,c in enumerate(initial)]
                else:cards=[None]*5
                size,step=((56,80),20) if game.hands==10 and index else (((83,119),30) if game.hands==5 and index else ((83,119),87))
                for i,card in enumerate(cards):
                    face=renderer.card(card,*size,disabled=not enabled)
                    image.paste(face,(x+i*step,y),face)
                following=snapshot['multipliers'][index] if phase=='ready' or (phase=='result' and reveal==5) else 1
                current=snapshot['active_multipliers'][index] if phase!='ready' and enabled else 1
                gutter=30 if game.hands==10 and index else 40
                def mult(number,top,height):
                    asset=renderer.assets['multipliers/'+str(number)+'x_2.png']
                    height=min(height,max(1,int(gutter*asset.height/asset.width)))
                    renderer._mult_art(image,number,x-3,top,height,1)
                if following>1:
                    renderer.paste(image,'multipliers/nexthand.png',(x-gutter,y+2),(gutter,18))
                    mult(following,y+23,16)
                if current>1:mult(current,y+height-29,24)
                if enabled and phase=='result' and reveal==5:renderer.win_indicator(image,index,snapshot['results'][index])
            for i,is_held in enumerate(held):
                if is_held and phase in ('hold','result'):
                    renderer.paste(image,'gui/hold.png',(44+41+87*i-24,375))
        finally:renderer.HANDS=old_layout
        self._board=image.resize((320,240),Image.Resampling.LANCZOS).crop((0,0,256,199))
        self._source,self._deal=image,deal
        self._key=key
        return self._board

    @staticmethod
    def _outline(image,mask,color,width=2):
        draw=ImageDraw.Draw(image)
        for i in range(5):
            if mask&(1<<i):
                left=math.floor((44+87*i)/2);right=math.ceil((44+87*i+83)/2)-1
                draw.rounded_rectangle((left-1,132,right+1,195),radius=2,outline=color,width=width)

    def render(self,play,trainer):
        if trainer.inline_waiting or trainer.inline_warning is not None:play._clear_notice()
        image=play.render()
        if play.menu is not None or play.notice:return image
        snapshot=dict(play._visual if play._visual is not None else play.session.snapshot())
        renderer=self.renderer(play)
        image.paste(self.board(snapshot,renderer),(0,0))
        draw=ImageDraw.Draw(image)
        # Preserve the original HELD pixels wherever focus/advice overlaps them.
        held_regions=[]
        for i,held in enumerate(snapshot['held']):
            if held:
                center=round((44+87*i+41)/2);box=(center-15,184,center+15,199)
                held_regions.append((box,image.crop(box)))
        if snapshot['phase']=='hold' and play.button_focus is None:
            i=play.selected_card;left=math.floor((44+87*i)/2);right=math.ceil((44+87*i+83)/2)-1
            center=round((44+87*i+41)/2)
            draw.rounded_rectangle((left-2,131,right+2,196),radius=3,outline=(0,0,0),width=4)
            draw.rounded_rectangle((left-1,132,right+1,195),radius=2,outline=GOLD,width=2)
            draw.polygon(((center-5,125),(center+5,125),(center,132)),fill=GOLD)
        actual=play.session.snapshot()
        report=None;original=None;mask=0;reveal=False
        if actual['phase']=='hold':
            mask=sum(1<<i for i,h in enumerate(actual['held']) if h)
            if trainer.report is not None and trainer._key==freeze_round(actual):
                report=trainer.report;original=actual
            reveal=trainer.settings['mode']=='coach' or trainer.inline_warning is not None or trainer.revealed_key==freeze_round(actual)
            if snapshot.get('_deal_reveal',5)<5:reveal=False
        elif trainer.last and trainer.last['snapshot']['game_id']==actual['game_id']:
            report=trainer.last['report'];original=trainer.last['snapshot'];mask=trainer.last['mask'];reveal=True
        if snapshot['phase']=='hold':
            if play.hint_visible and play._advice:
                if play._advice['mask']:self._outline(image,play._advice['mask'],(255,32,32))
                elif play._draw_hint_step is None or play._draw_hint_step%2==0:renderer.red_draw_button(image)
            elif report and reveal:
                if report['mask']:self._outline(image,report['mask'],GREEN)
                else:draw.rounded_rectangle((276,218,318,233),radius=3,outline=GREEN,width=2)
        for box,pixels in held_regions:image.paste(pixels,box[:2])
        self.sidebar(image,renderer,trainer,actual,report,original,mask,reveal)
        return image

    def sidebar(self,image,r,t,snapshot,report,original,mask,reveal):
        stats=t.state.current['stats'] if t.state.current and t.state.current['game_id']==snapshot['game_id'] else t.state.totals(snapshot['game_id'])
        scores=None if report is None else (report['mask'],report['value'],
            tuple((m,report['holds'][m]['value']) for m in report['ranking'][:3]),
            tuple(report['holds'][mask][k] for k in ('value','current','future')))
        key=Renderer._freeze((self.tab,t.settings['mode'],t.inline_waiting,t.inline_warning,
            t.analysis_failed,snapshot['game_id'],snapshot['phase'],snapshot['active_multipliers'],
            snapshot['multipliers'],mask,reveal,scores,stats,bool(t.play.autoplay),
            original['initial'] if original else None))
        if key!=self._sidebar_key:
            self._draw_sidebar(image,r,t,snapshot,report,original,mask,reveal)
            self._sidebar_image=image.crop((256,0,320,199));self._sidebar_key=key
        else:image.paste(self._sidebar_image,(256,0))

    def _draw_sidebar(self,image,r,t,snapshot,report,original,mask,reveal):
        draw=ImageDraw.Draw(image);draw.rectangle((256,0,319,198),fill=BG)
        draw.line((256,0,256,198),fill=(92,100,146))
        def text(y,value,color=WHITE,size=8,bold=False):
            r.fitted_label(image,(260,y,317,y+12),str(value),size,color,bold)
        mode=t.settings['mode'].upper()
        text(2,mode if self.tab==0 else ('HOLD EV' if self.tab==1 else 'STATS'),GOLD,10,True)
        loss=max(0,report['value']-report['holds'][mask]['value']) if report else 0
        if t.inline_waiting:status='ANALYZING'
        elif t.inline_warning is not None:status='FIX / DOWN' if loss>TOLERANCE else 'CORRECT'
        elif snapshot['phase']=='result':status='LAST HAND'
        elif snapshot['phase']=='ready':status='READY'
        elif t.analysis_failed:status='RETRY DOWN'
        elif t.settings['mode']=='off':status='UNGRADED'
        elif report is None:status='ANALYZING'
        else:status='YOUR HOLD'
        text(16,status,RED if t.inline_warning is not None and loss>TOLERANCE else MUTED,7)
        draw.line((260,29,316,29),fill=(47,58,92))
        stats=t.state.current['stats'] if t.state.current and t.state.current['game_id']==snapshot['game_id'] else t.state.totals(snapshot['game_id'])
        automatic=bool(t.play.autoplay)
        if automatic:stats=autoplay_stats(stats)
        accuracy='--' if not stats['decisions'] else '%.1f%%'%(100*stats['correct']/stats['decisions'])
        if self.tab==2:
            rows=[('AUTO ACC' if automatic else 'ACCURACY',accuracy),
                  ('CHECKED' if automatic else 'DECISIONS',('%s/%s'%(stats['decisions'],stats['_auto_total'])) if automatic else stats['decisions']),('ERRORS',stats['errors']),
                  ('EV LOST','%.3f'%stats['ev_lost']),('ASSISTED',stats['assisted']),
                  ('NET','%+d'%(stats['returned']-stats['wagered'])),('HANDS',stats['hands'])]
            if automatic:rows[4]=('CORRECT',stats['correct'])
            for i,(label,value) in enumerate(rows):text(34+22*i,label,MUTED,7);text(44+22*i,value,GOLD,9,True)
            return
        if self.tab==1 and report and reveal:
            text(33,'TOP HOLDS',MUTED,7)
            for i,m in enumerate(report['ranking'][:3]):
                text(45+25*i,'%d: %s'%(i+1,positions(m)),GOLD if i==0 else WHITE,8,True)
                text(56+25*i,'%.3f'%report['holds'][m]['value'],GOLD if i==0 else WHITE,8)
            entry=report['holds'][mask]
            text(123,'CURRENT EV',MUTED,7);text(133,'%.3f'%entry['current'],WHITE,9)
            text(149,'FUTURE EV',MUTED,7);text(159,'%.3f'%entry['future'],WHITE,9)
            text(177,'LOSS %.3f'%loss,RED if loss>TOLERANCE else GREEN,8)
            return
        if self.tab==1:
            text(52,'MAKE YOUR',MUTED,8)
            text(65,'OWN HOLD',MUTED,8)
            text(94,'DOWN WILL',WHITE,8)
            text(107,'CHECK EV',WHITE,8)
            return
        text(33,'BEST HOLD',MUTED,7)
        text(43,positions(report['mask']) if report and reveal else '--',GOLD,10,True)
        text(59,'BEST EV',MUTED,7)
        text(69,'%.3f'%report['value'] if report and reveal else '--',GOLD,9,True)
        text(86,'YOU '+positions(mask),WHITE,8)
        text(99,'EV %.3f'%report['holds'][mask]['value'] if report and reveal else 'EV --',WHITE,8)
        text(112,'LOSS %.3f'%loss if report and reveal else 'LOSS --',RED if report and reveal and loss>TOLERANCE else GREEN,8)
        draw.line((260,125,316,125),fill=(47,58,92))
        text(130,('AUTO ' if automatic else 'ACC ')+accuracy,WHITE,8)
        text(142,'ERR %s/%s'%(stats['errors'],stats['decisions']),WHITE,8)
        text(154,'LOST %.2f'%stats['ev_lost'],GOLD,8)
        text(166,'X SUM %s'%sum(snapshot['active_multipliers'] if snapshot['phase']!='ready' else snapshot['multipliers']),MUTED,7)
        if original:
            for i,card in enumerate(original['initial']):
                x=259+12*i
                draw.rounded_rectangle((x,180,x+10,197),radius=1,fill=(245,245,240))
                rank='JK' if card==52 else '23456789TJQKA'[card%13]
                suit='' if card==52 else 'CDHS'[card//13]
                color=(210,0,0) if suit in ('D','H') else (0,0,0)
                r.fitted_label(image,(x,181,x+10,189),rank,7,color,True)
                r.fitted_label(image,(x,190,x+10,197),suit,6,color,True)
