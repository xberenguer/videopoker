"""Current-image-bound tour. No production source or IMG is changed."""
import copy,hashlib,json,random,shutil,sys,time
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_ui import PokerUI
from poker_engine import Session
from poker_training import TrainingState
from poker_training_store import Journal,TrainingStore
OUT=Path(__file__).resolve().parent
proof=json.loads((ROOT/'validation/artifact-readback-v066.json').read_text())
for name,sha in proof['runtime_sha256'].items():assert hashlib.sha256((ROOT/'payload'/name).read_bytes()).hexdigest()==sha
image=Path(proof['image']);assert hashlib.sha256(image.read_bytes()).hexdigest()==proof['image_sha256']
temp=None
class Clock:
    now=0.
    def __call__(self):return self.now
clock=Clock();store=TrainingStore.hardware();state=TrainingState(store,clock)
app=PokerApp(play=PokerUI(Session(game_id='ddb10',rng=random.Random(8841)),cabinet=True,clock=clock),training_state=state)
t=app.trainer;ui=app.play;frames={}
def save(name):
    ui._finish_animation();app.render().save(OUT/(name+'.png'));frames[name]=hashlib.sha256((OUT/(name+'.png')).read_bytes()).hexdigest()
def wait():
    deadline=time.monotonic()+12
    while t._token is not None and time.monotonic()<deadline:t.update(clock());time.sleep(.001)
    assert t.report

def deal():
    ui._finish_animation();ui.session.deal();wait()

def choose(mask):ui.session.held=[bool(mask&(1<<i)) for i in range(5)]
try:
    ui.menu['index']=9;app.toggle_hidden_mode()
    for i in range(4):
        deal();report=t.report
        if i%2:
            choose(min(report['holds'],key=lambda row:row['value'])['mask']);ui._play()
            assert t.inline_warning is not None
            if i==1:choose(report['mask'])
            ui._play()
        else:choose(report['mask']);ui._play()
        ui._finish_animation()
    assert state.totals('ddb10')['decisions']==4
    assert state.totals('ddb10')['errors']==2
    t.page='stats';t.stats_scope=0;save('full-session-stats')
    t.stats_scope=1;save('all-session-stats')
    state.begin('ddb10')  # Keep a real previous-session view for the tour.
    t.page='errors';t.index=0;save('error-list')
    app.handle('CENTER');assert t.page=='error_detail';save('review-error')
    app.handle('CENTER');assert ui.session.phase=='hold' and t.replay is not None
    wait();save('replay-original-board')
    choose(t.report['mask']);ui._play();ui._finish_animation()
    assert state.errors('ddb10',learned=True)[0]['learned']
    t.page='errors';t.index=0;save('learned-error')
    t.page='stats';t.stats_scope=4;save('saved-session-stats')
    t.page='settings';t.index=3;t.settings['dynamic']=True;save('dynamic-replay-settings')
    t.settings['dynamic']=False;t.settings['practice']='errors';t.index=4;save('errors-only-settings')
    t.settings['practice']='random';t.settings['difficulty']='close';t.index=5;save('close-drill-settings')
    t.dismiss();deal();save('curated-close-drill')
    t.settings['difficulty']='clear';t.page='settings';t.index=5;save('clear-drill-settings')
    t.dismiss();choose(t.report['mask']);ui._play();ui._finish_animation();deal();save('curated-clear-drill')
    t.settings['difficulty']='all';t.settings['mode']='coach';t.revealed_key=t._key
    t.open_ev();wait();t.index=0;save('full-hold-ranking')
    app.handle('CENTER');assert t.page=='ev_detail';save('payout-ev-detail')
    t.detail_scroll=6;save('payout-detail-more')
    t.dismiss();choose(t.report['mask']);ui._play();ui._finish_animation()
    t.settings.update(mode='test',practice='random',difficulty='all',dynamic=False)
    state.begin('ddb10')
    ui.autoplay=True;ui.autoplay_speed=0;ui._auto_stage='manual-deal';ui._auto_due=None
    for speed in (0,1,2):
        if speed:ui._cycle_autoplay_speed()
        target=ui.session.rounds+3;deadline=time.monotonic()+20;last_manual=None
        while ui.session.rounds<target and time.monotonic()<deadline:
            if speed==0:
                key=(ui.session.rounds,ui.session.phase)
                if key!=last_manual:app.handle('DOWN');last_manual=key
            clock.now+=.06;app.update(clock());time.sleep(.001)
            assert ui.autoplay,ui.notice
        assert ui.session.rounds==target
        deadline=time.monotonic()+15
        while state.current['stats']['auto_checked']<3*(speed+1) and time.monotonic()<deadline:
            t.update(clock());time.sleep(.001)
        assert state.current['stats']['auto_checked']==3*(speed+1)
        assert state.current['stats']['auto_errors']==0
        app.training_hud.tab=2;save('autoplay-'+('M','medium','fast')[speed]+'-live')
    app.training_hud.tab=0;save('autoplay-advice-live')
    t.open();t.index=3;app.handle('CENTER');assert t.stats_scope==2
    save('autoplay-session-stats')
    t.stats_scope=3;save('autoplay-all-stats')
    t.page='home';store.flush();save('hidden-options-saved')
    for index in (0,1,2):t.page='help';t.index=index;save('guide-'+str(index+1))
    t.dismiss();app.toggle_calculator();c=app.calculator;c.select_game('ddb10')
    for i,card in enumerate((12,4,40,46,5)):c.set_card(i,card)
    for i in range(10):c.set_multiplier(i,12)
    c.calculate();deadline=time.monotonic()+12
    while c._token is not None and time.monotonic()<deadline:c.update(clock());time.sleep(.001)
    assert c.result
    save('calculator-result');c.page='multipliers';save('calculator-multipliers')
    c.page='pays';save('calculator-pays');c.page='picker';save('calculator-card-entry')
    c.page='editor';c.focus=8;app.handle('KEY2');assert t.page=='ev';wait();save('calculator-full-ev')
    state.save();assert store.flush()
    summary={'version':'0.6.6','production_image_sha256':proof['image_sha256'],'screenshots':frames,'fixture':'Actual runtime with seeded demo rounds; RAM-only history; no SD or physical device accessed','recorded_totals':copy.deepcopy(state.totals('ddb10'))}
finally:
    app.close()
    if 'summary' in globals():
        fresh_store=TrainingStore.hardware();fresh=TrainingState(fresh_store)
        assert not fresh_store.persistent and fresh_store._thread is None
        assert not fresh.data['totals'] and not fresh.data['settings'] and not fresh.data['sessions']
        fresh_store.close();summary['RAM_only_runtime_verified']=True
# Compare only existing, verified production renderer frames.
base=ROOT/'validation/live-training-v066'
font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',19)
pairs=[
('01-live-modes',[(base/'04-test-live.png','TEST: decide before seeing the answer'),(base/'07-coach-live.png','COACH: recommended hold shown immediately')]),
('02-decision-feedback',[(base/'05-inline-error.png','Incorrect hold: advice and loss stay beside the cards'),(base/'06-result-feedback.png','After Draw: original decision and results')]),
('03-live-panels',[(base/'08-live-ev.png','Live EV: three ranked holds, current and future value'),(base/'09-live-stats.png','Live stats: accuracy, errors, EV loss and actual net')]),
('04-full-ev',[(OUT/'full-hold-ranking.png','Full EV: scroll through every one of the 32 holds'),(OUT/'payout-ev-detail.png','Selected hold: outcome probabilities and EV contributions')]),
('05-error-review',[(OUT/'error-list.png','Recorded errors for the selected game'),(OUT/'review-error.png','Review cards, chosen hold, best hold and multipliers')]),
('06-error-replay',[(OUT/'replay-original-board.png','Replay the original cards AND multiplier board'),(OUT/'learned-error.png','Correct replay marks the error learned')]),
('07-detailed-statistics',[(OUT/'full-session-stats.png','Full session: accuracy, credits, EV retained, assistance'),(OUT/'all-session-stats.png','Combined statistics from sessions this power-on')]),
('08-training-options',[(OUT/'hidden-options-saved.png','Hidden options: RAM history, full reports and calculator'),(OUT/'dynamic-replay-settings.png','TEST / COACH, warnings, recording and dynamic replay')]),
('09-practice',[(OUT/'errors-only-settings.png','Practice only errors you previously made'),(OUT/'close-drill-settings.png','Close / Clear difficulty drills; fixed 1x boards')]),
('10-calculator',[(OUT/'calculator-card-entry.png','Manual card entry for all twelve games'),(OUT/'calculator-result.png','Best hold with current + future multipliers')]),
('11-calculator-controls',[(OUT/'calculator-multipliers.png','Individual or whole-board multipliers'),(OUT/'calculator-pays.png','Review the selected preset paytable')]),
('14-calculator-inline-ev',[(OUT/'calculator-result.png','Inline EV includes current and future multiplier value'),(OUT/'calculator-full-ev.png','Optional full table: all 32 hold alternatives')]),
('13-autoplay',[(OUT/'autoplay-fast-live.png','Live automatic accuracy, coverage, EV loss and net'),(OUT/'autoplay-session-stats.png','Session Autoplay: graded actual played holds')]),
('12-other-layouts',[(base/'15-ddb3-live.png','Three-hand training layout'),(base/'15-dw5-live.png','Five-hand Deuces Wild training layout')])]
for name,items in pairs:
    sheet=Image.new('RGB',(1280,518),(7,10,25));draw=ImageDraw.Draw(sheet)
    for i,(path,title) in enumerate(items):
        draw.text((i*640+9,9),title,font=font,fill=(245,222,90))
        sheet.paste(Image.open(path).convert('RGB').resize((640,480),Image.Resampling.NEAREST),(i*640,38))
    sheet.save(OUT/(name+'.png'))
summary['paired_galleries']=[name+'.png' for name,_ in pairs]
(OUT/'manifest.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'new_native_frames':len(frames),'paired_galleries':len(pairs),'output':str(OUT)}))
