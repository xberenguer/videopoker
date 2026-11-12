#!/usr/bin/env python3
"""Local stock-ARM strategy/UI diagnostic guest for probe_arm_guest.py.

This is a functional check with a fake presentation clock. It deliberately makes
no wall-clock button sampling, GPIO, LCD, signing or physical-Pi speed claim.
The ordinary full ARM probe and any failed timing report remain separate.
"""

GUEST = r'''import hashlib, json, math, os, random, sys, time, traceback, threading
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, '/opt/dino')
out = Path('/poker-proof')
watcher_stop = watcher_thread = None
def stage(name):
    (out/'arm-stage.txt').write_text(name+'\n')
    os.sync()
try:
    stage('strategy-functional-python-entered')
    import PIL
    from PIL import ImageChops
    from poker_engine import Session
    from poker_strategy import StrategyAdvisor, StrategyTable, _round
    from poker_ui import PokerUI
    # Diagnostic only: observe a blocked main thread without changing entropy,
    # game behavior, solver assertions, or any production code.
    main_ident = threading.current_thread().ident
    watcher_stop = threading.Event()
    def proc_text(path):
        try:
            return Path(path).read_text().strip()
        except Exception as error:
            return type(error).__name__+': '+str(error)
    def diagnose_stall():
        while not watcher_stop.wait(10.0):
            try:
                frames = sys._current_frames()
                main_frame = frames.get(main_ident)
                task_waits = {}
                try:
                    for task in Path('/proc/self/task').iterdir():
                        task_waits[task.name] = proc_text(str(task/'wchan'))
                except Exception as error:
                    task_waits['error'] = str(error)
                record = {
                    'stage':proc_text(str(out/'arm-stage.txt')),
                    'monotonic':time.monotonic(),
                    'main_python_stack':traceback.format_stack(main_frame) if main_frame is not None else [],
                    'thread_stacks':{str(ident):traceback.format_stack(frame)
                                     for ident,frame in frames.items()},
                    'main_wchan':proc_text('/proc/self/wchan'),
                    'main_syscall':proc_text('/proc/self/syscall'),
                    'entropy_avail':proc_text('/proc/sys/kernel/random/entropy_avail'),
                    'thread_wchan':task_waits,
                    'scope':'Diagnostic observations only; no entropy injection or production changes'}
                (out/'arm-stall.json').write_text(json.dumps(record,indent=2)+'\n')
                os.sync()
            except BaseException:
                (out/'arm-stall-error.txt').write_text(traceback.format_exc())
                os.sync()
    watcher_thread = threading.Thread(target=diagnose_stall,name='arm-diagnostic-watcher')
    watcher_thread.daemon = True
    watcher_thread.start()
    stage('strategy-functional-imports-complete')
    started = time.monotonic()
    stage('strategy-table-before-constructor')
    table = StrategyTable()
    stage('strategy-table-after-constructor')
    known = (((12,25,38,1,2),7), ((0,1,2,3,17),31),
             ((11,24,37,50,12),31), ((0,15,30,44,12),16))
    stage('fixture-before-random')
    fixture_rng = random.Random(1)
    stage('fixture-after-random-before-session')
    fixture = Session(rng=fixture_rng)
    stage('fixture-after-session-before-deal')
    fixture.deal()
    stage('fixture-after-deal')
    cases = []
    for case_index, (cards, expected) in enumerate(known,1):
        stage('known-case-%d-before-fixture' % case_index)
        fixture.initial = list(cards)
        fixture.hands = [list(cards) for _ in range(10)]
        fixture.active_multipliers = [1]*10
        stage('known-case-%d-before-advise' % case_index)
        answer = table.advise(_round(fixture.snapshot()))
        stage('known-case-%d-after-advise' % case_index)
        assert answer['mask'] == expected, (cards, expected, answer)
        variations = []
        for multiplier in (2,4,8,12):
            fixture.active_multipliers = [multiplier]*10
            stage('known-case-%d-sum-%d-before-advise' % (case_index,10*multiplier))
            varied = table.advise(_round(fixture.snapshot()))
            stage('known-case-%d-sum-%d-after-advise' % (case_index,10*multiplier))
            assert type(varied['mask']) is int and 0 <= varied['mask'] < 32
            assert math.isfinite(varied['value']) and varied['expected_current_win'] >= 0
            assert varied['feature'] and varied['continuation_bellman_span'] == table.certificate
            variations.append({'multiplier_sum':10*multiplier,'mask':varied['mask'],
                               'expected_current_win':varied['expected_current_win']})
        cases.append({'cards':list(cards),'multiplier_sum':10,
                      'expected_mask':expected,'actual_mask':answer['mask'],
                      'variations':variations})
    stage('strategy-functional-known-cases-complete')

    frames = {}
    def plain_render(ui):
        state = dict(ui._visual if ui._visual is not None else ui.session.snapshot())
        state['_button_focus'] = ui.button_focus
        state['_speed'] = ui.autoplay_display_speed if ui.autoplay else ui.speed
        state['_badge_frame'] = ui._badge_frame
        return ui.renderer.render(state, ui.selected_card, ui.selected_hand, ui.menu)
    def capture(ui, name):
        image = ui.render()
        assert image.size == (320,240) and image.mode == 'RGB', (name,image.size,image.mode)
        image.save(out/(name+'.png'))
        frames[name] = {'phase':ui.session.snapshot()['phase'],
                        'autoplay':ui.autoplay,'hint_visible':ui.hint_visible,
                        'native_resolution':[320,240],'mode':image.mode}

    def assert_auto_indicator(ui):
        image, normal = ui.render(), plain_render(ui)
        bounds = ImageChops.difference(image, normal).getbbox()
        assert bounds is not None and bounds[0]>=246 and bounds[1]>=205 and bounds[2]<=(264 if ui.manual_autoplay else 262) and bounds[3]<=217
        assert (255,255,0) in set(image.crop((246,205,262,217)).getdata())
        icon_count = list(image.crop((256,207,262,214)).getdata()).count((255,255,0))
        assert icon_count>0
        if ui.autoplay_speed in (1,2):
            assert image.getpixel((257,209))[0]>128 and image.getpixel((257,210))[0]>128
            assert (255,255,0) not in set(image.crop((256,207,262,208)).getdata())
            assert (255,255,0) not in set(image.crop((256,212,262,214)).getdata())
            if ui.autoplay_speed==1:
                assert (255,255,0) not in set(image.crop((259,208,262,212)).getdata())
        image.paste(normal.crop((246,205,264,217)), (246,205))
        assert image.tobytes() == normal.tobytes(), 'Only the A and speed icon may differ during autoplay'

    # The production advisor runs asynchronously. Only presentation time is
    # synthetic; fixture outcomes come from explicitly injected random.Random.
    manual_clock = [0.0]
    stage('manual-before-random-session')
    manual_game = Session(rng=random.Random(1))
    stage('manual-after-session-before-advisor')
    manual_advisor = StrategyAdvisor()
    stage('manual-after-advisor-before-ui')
    manual_ui = PokerUI(session=manual_game,clock=lambda:manual_clock[0],advisor=manual_advisor)
    stage('manual-after-ui')
    manual_ui.speed = 2
    capture(manual_ui,'ready')
    assert manual_ui.handle('DOWN')
    assert manual_game.snapshot()['phase'] == 'hold'
    manual_clock[0] = 1.0
    manual_ui.update(manual_clock[0])
    capture(manual_ui,'hold')
    before_hint = manual_game.snapshot()
    manual_ui.set_pressed_mask(1)
    manual_ui.handle_sampled('UP',1.0)
    deadline = time.monotonic()+90
    while manual_ui._advice is None and time.monotonic()<deadline:
        manual_ui.update(manual_clock[0])
        assert not manual_ui.notice, manual_ui.notice
        time.sleep(.005)
    assert manual_ui._advice is not None and not manual_ui.hint_visible
    assert manual_ui.render().tobytes() == plain_render(manual_ui).tobytes()
    manual_clock[0] += PokerUI.HINT_HOLD_SECONDS+.001
    manual_ui.update(manual_clock[0])
    assert manual_ui.hint_visible
    assert manual_game.snapshot() == before_hint, 'A hint must not alter held cards or game state'
    capture(manual_ui,'hint-on')
    hint_mask = manual_ui._advice['mask']
    assert hint_mask != 0, 'Fixture must visibly recommend at least one held card'
    assert manual_ui.render().tobytes() != plain_render(manual_ui).tobytes()
    # Held UP remains solid red across presentation time; release removes all
    # advice rendering without changing the poker session. Read-only advice
    # remains cached so the first gesture need not restart cold table loading.
    manual_clock[0] += 2.0
    manual_ui.update(manual_clock[0])
    assert manual_ui.hint_visible
    assert manual_ui.render().tobytes() != plain_render(manual_ui).tobytes()
    assert manual_game.snapshot() == before_hint
    manual_ui.set_pressed_mask(0)
    manual_ui.update(manual_clock[0])
    assert not manual_ui.hint_visible
    assert manual_ui._advisor_token is None and manual_ui._advice['mask'] == hint_mask
    assert manual_ui.render().tobytes() == plain_render(manual_ui).tobytes()
    assert manual_game.snapshot() == before_hint
    # Manual double-tap uses the same production advisor, never Deal/Draw.
    manual_clock[0] += .5
    for _ in range(2):
        manual_ui.set_pressed_mask(1); manual_ui.handle('UP'); manual_ui.set_pressed_mask(0)
        manual_clock[0] += .1
    assert manual_game.snapshot()==before_hint and not manual_ui.autoplay
    manual_clock[0] += manual_ui.UP_CLICK_GAP_SECONDS+manual_ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
    deadline = time.monotonic()+90
    while time.monotonic()<deadline:
        manual_ui.update(manual_clock[0])
        if manual_ui._manual_hold_key is None and manual_ui._manual_up_due is None: break
        time.sleep(.005)
    assert manual_game.held==[bool(hint_mask & (1<<i)) for i in range(5)]
    after_best_hold=manual_game.snapshot(); after_best_hold['held']=before_hint['held']
    assert after_best_hold==before_hint and not manual_ui.autoplay
    capture(manual_ui,'manual-best-hold')
    manual_ui.close()
    assert not manual_advisor._thread.is_alive()
    # Actual zero-hold strategy, not a synthetic UI mask.
    draw_clock=[0.0]
    class DrawFiveSampler:
        def sample(self,population,count): return [26,20,41,43,6]
    draw_game=Session(rng=DrawFiveSampler());draw_game.deal()
    draw_before=draw_game.snapshot();draw_advisor=StrategyAdvisor()
    draw_ui=PokerUI(session=draw_game,clock=lambda:draw_clock[0],advisor=draw_advisor)
    draw_ui.speed=2;draw_ui.set_pressed_mask(1);draw_ui.handle('UP')
    deadline=time.monotonic()+90
    while draw_ui._advice is None and time.monotonic()<deadline:
        draw_ui.update(draw_clock[0]);time.sleep(.005)
    assert draw_ui._advice is not None and draw_ui._advice['mask']==0
    assert not draw_ui.hint_visible and draw_ui.render().tobytes()==plain_render(draw_ui).tobytes()
    draw_clock[0]=PokerUI.HINT_HOLD_SECONDS+.001;draw_ui.update(draw_clock[0])
    bright=draw_ui.render();capture(draw_ui,'draw-hint')
    box=ImageChops.difference(bright,plain_render(draw_ui)).getbbox()
    assert box is not None and box[0]>=275 and box[1]>=218 and box[2]<=319 and box[3]<=234
    draw_clock[0]+=PokerUI.HINT_DRAW_FLASH_SECONDS/2;draw_ui.update(draw_clock[0])
    dim=draw_ui.render();capture(draw_ui,'draw-hint-pulse')
    assert dim.tobytes()==plain_render(draw_ui).tobytes()
    draw_clock[0]+=PokerUI.HINT_DRAW_FLASH_SECONDS/2;draw_ui.update(draw_clock[0])
    assert draw_ui.render().crop((275,218,319,234)).tobytes()==bright.crop((275,218,319,234)).tobytes()
    draw_clock[0]+=2;draw_ui.update(draw_clock[0])
    assert draw_ui.render().crop((275,218,319,234)).tobytes()==bright.crop((275,218,319,234)).tobytes()
    draw_ui.set_pressed_mask(0);draw_ui.update(draw_clock[0])
    assert not draw_ui.hint_visible and draw_ui.render().tobytes()==plain_render(draw_ui).tobytes()
    assert draw_game.snapshot()==draw_before
    draw_ui.close();assert not draw_advisor._thread.is_alive()
    stage('strategy-functional-hint-render-complete')

    auto_clock = [0.0]
    stage('auto-before-random-session')
    auto_game = Session(rng=random.Random(250))
    stage('auto-after-session-before-advisor')
    auto_advisor = StrategyAdvisor()
    stage('auto-after-advisor-before-ui')
    auto_ui = PokerUI(session=auto_game,clock=lambda:auto_clock[0],advisor=auto_advisor)
    stage('auto-after-ui')
    auto_ui.speed = 2
    auto_ui.autoplay_speed = 1
    # Separate captured clicks never become an activation when drained together.
    for captured in (0.0,.60,1.20):
        auto_clock[0] = captured+.05
        auto_ui.set_pressed_mask(1)
        auto_ui.handle_sampled('UP',captured)
        auto_ui.set_pressed_mask(0)
        auto_ui.update(auto_clock[0])
    assert not auto_ui.autoplay and auto_game.snapshot()['phase'] == 'ready'
    assert auto_game.credits == 10000
    auto_ui.pause_autoplay()
    # Three captured clicks .20s apart activate autoplay even when presentation
    # dispatch timestamps are a full second apart. This checks logical time
    # propagation, not wall-clock sampler performance or physical GPIO.
    for index,captured in enumerate((1.50,1.70,1.90)):
        auto_clock[0] = 2.0+index
        auto_ui.set_pressed_mask(1)
        auto_ui.handle_sampled('UP',captured)
        auto_ui.set_pressed_mask(0)
        if index<2: assert not auto_ui.autoplay
    assert auto_ui.manual_autoplay
    for _ in range(2):
        auto_clock[0] += .1
        auto_ui.set_pressed_mask(1); auto_ui.handle('UP'); auto_ui.set_pressed_mask(0)
    auto_clock[0] += auto_ui.UP_CLICK_GAP_SECONDS+auto_ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
    auto_ui._commit_auto_up()
    assert auto_ui.autoplay_speed == 1
    auto_ui.set_pressed_mask(0)
    assert not auto_ui.hint_visible
    captured_autoplay = captured_result = False
    consider_started = draw_started = result_started = None
    pacing_checks = {'consider':0, 'draw':0, 'result':0, 'one_card_per_update':0}
    timeline = []
    previous = auto_game.snapshot()
    previous_stage = auto_ui._auto_stage
    deadline = time.monotonic()+120
    while auto_game.rounds < 3 and time.monotonic()<deadline:
        auto_clock[0] += .05
        auto_ui.update(auto_clock[0])
        assert not auto_ui.notice, auto_ui.notice
        current = auto_game.snapshot()
        phase, current_stage = current['phase'], auto_ui._auto_stage
        assert not auto_ui.hint_visible
        if current_stage != previous_stage:
            timeline.append({'time':round(auto_clock[0],3),'stage':current_stage,
                             'phase':phase,'completed_rounds':auto_game.rounds})
        if current_stage == 'consider' and previous_stage != 'consider':
            consider_started = auto_clock[0]
        if current_stage == 'select' and previous_stage == 'consider':
            assert consider_started is not None
            assert auto_clock[0]-consider_started >= 3.2-1e-7
            pacing_checks['consider'] += 1
        if current_stage == 'draw' and previous_stage != 'draw':
            draw_started = auto_clock[0]
        if phase == 'result' and previous['phase'] == 'hold':
            assert draw_started is not None
            assert auto_clock[0]-draw_started >= .28-1e-7
            pacing_checks['draw'] += 1
        if current_stage == 'result' and previous_stage != 'result':
            result_started = auto_clock[0]
        if phase == 'hold' and previous['phase'] == 'result':
            assert result_started is not None
            assert auto_clock[0]-result_started >= 1.35-1e-7
            pacing_checks['result'] += 1
        if phase == previous['phase'] == 'hold' and current['initial'] == previous['initial']:
            assert sum(a != b for a,b in zip(current['held'],previous['held'])) <= 1
            pacing_checks['one_card_per_update'] += 1
        if current_stage in ('select','draw') and any(current['held']) and not captured_autoplay:
            assert_auto_indicator(auto_ui)
            capture(auto_ui,'autoplay')
            captured_autoplay = True
        if phase == 'result' and not captured_result:
            assert_auto_indicator(auto_ui)
            capture(auto_ui,'result')
            captured_result = True
        previous, previous_stage = current, current_stage
        time.sleep(.005)
    assert auto_game.rounds >= 3 and auto_ui.autoplay, auto_game.snapshot()
    assert captured_autoplay and captured_result
    assert pacing_checks['consider'] >= 3 and pacing_checks['draw'] >= 3
    assert pacing_checks['result'] >= 2 and pacing_checks['one_card_per_update'] > 0
    assert auto_ui.AUTO_CONSIDER_SECONDS == 3.2
    assert auto_ui.AUTO_SELECT_SECONDS == .24
    assert auto_ui.AUTO_HOLD_SECONDS == .28
    assert auto_ui.AUTO_RESULT_SECONDS == 1.35
    speed_double_checks=[]
    for expected in (2,0,1):
        frozen=auto_game.snapshot(); previous_speed=auto_ui.autoplay_speed
        for _ in range(2):
            auto_ui.set_pressed_mask(1);auto_ui.handle('UP');auto_ui.set_pressed_mask(0)
            auto_clock[0] += .1
        assert auto_ui.autoplay and auto_ui.autoplay_speed==previous_speed
        auto_clock[0] += auto_ui.UP_CLICK_GAP_SECONDS+auto_ui.UP_TAP_COMMIT_GRACE_SECONDS+.01
        auto_ui.update(auto_clock[0])
        assert auto_ui.autoplay and auto_ui.autoplay_speed==expected
        assert auto_game.snapshot()==frozen and not auto_ui.hint_visible
        assert_auto_indicator(auto_ui)
        speed_double_checks.append(expected)
    # Holding a single UP cannot select a pace.
    auto_ui.set_pressed_mask(1);auto_ui.handle('UP')
    auto_clock[0] += 2
    auto_ui.update(auto_clock[0]);auto_ui.set_pressed_mask(0)
    assert auto_ui.autoplay and auto_ui.autoplay_speed==1
    paused=auto_game.snapshot();selected=auto_ui.selected_card
    for index in range(3):
        auto_clock[0] += .1
        auto_ui.set_pressed_mask(1);auto_ui.handle('UP');auto_ui.set_pressed_mask(0)
        assert auto_ui.autoplay_speed==1
        if index<2: assert auto_ui.autoplay
    assert not auto_ui.autoplay and auto_ui.autoplay_speed==1 and auto_game.snapshot()==paused
    for index in range(3):
        auto_clock[0] += .1
        auto_ui.set_pressed_mask(1);auto_ui.handle('UP');auto_ui.set_pressed_mask(0)
        if index<2: assert not auto_ui.autoplay
    assert auto_ui.manual_autoplay and auto_game.snapshot()==paused
    auto_ui.handle('LEFT')
    assert not auto_ui.autoplay and auto_ui.selected_card==selected
    assert auto_ui.render().tobytes()==plain_render(auto_ui).tobytes()
    auto_clock[0] += 100
    auto_ui.update(auto_clock[0])
    assert auto_game.snapshot()==paused and not auto_ui.autoplay
    auto_ui.close()
    assert not auto_advisor._thread.is_alive()
    # Actual strategy worker: two DOWN presses per M-mode round.
    mode_clock=[0.0];mode_game=Session(rng=random.Random(250));mode_advisor=StrategyAdvisor()
    mode_ui=PokerUI(mode_game,clock=lambda:mode_clock[0],advisor=mode_advisor)
    assert mode_ui.autoplay_speed==0
    mode_ui.autoplay_speed=2  # A fresh activation must forget the old speed.
    assert [p['name'] for p in mode_ui.AUTO_PROFILES]==['manual','medium','fast']
    for _ in range(3):
        mode_clock[0]+=.1
        mode_ui.set_pressed_mask(1);mode_ui.handle('UP');mode_ui.set_pressed_mask(0)
    mode_ui.update(mode_clock[0]);ready=mode_game.snapshot()
    mode_clock[0]+=100;mode_ui.update(mode_clock[0])
    assert mode_ui.manual_autoplay and mode_ui._auto_stage=='manual-deal'
    assert mode_game.snapshot()==ready and mode_game.credits==10000
    for cycle in range(2):
        previous=mode_game.snapshot();mode_ui.handle('DOWN')
        assert mode_ui.manual_autoplay and mode_game.phase=='hold'
        assert mode_ui._auto_stage=='manual-draw' and mode_ui._animation is None
        assert mode_game.credits==previous['credits']-previous['total_bet']
        assert mode_game.active_multipliers==previous['multipliers']
        mode_ui.on_input_reset()
        assert mode_ui.manual_autoplay and not mode_ui._manual_auto_draw_requested
        mode_ui.update(mode_clock[0])
        deadline=time.monotonic()+120
        while mode_ui._advice is None and time.monotonic()<deadline:
            mode_ui.update(mode_clock[0]);time.sleep(.005)
        assert mode_ui._advice is not None and not mode_ui._manual_auto_draw_requested
        expected_mask=mode_ui._advice['mask'];dealt=mode_game.snapshot()
        assert dealt['held']==[False]*5
        mode_clock[0]+=1000;mode_ui.update(mode_clock[0])
        assert mode_game.snapshot()==dealt and mode_ui._auto_stage=='manual-draw'
        if cycle==0:
            assert_auto_indicator(mode_ui);capture(mode_ui,'autoplay-manual')
        command_time=mode_clock[0];mode_ui.handle('DOWN')
        assert mode_clock[0]==command_time and mode_ui._animation is None
        assert mode_ui.manual_autoplay and mode_game.phase=='result'
        assert mode_game.held==[bool(expected_mask&(1<<i)) for i in range(5)]
        assert mode_ui._auto_stage=='manual-deal' and mode_game.rounds==cycle+1
        assert mode_ui._auto_due is None and not mode_ui._manual_auto_draw_requested
        assert_auto_indicator(mode_ui)
        if cycle==0:capture(mode_ui,'autoplay-manual-wait')
        waiting=mode_game.snapshot();mode_clock[0]+=1000;mode_ui.update(mode_clock[0])
        assert mode_game.snapshot()==waiting
    waiting=mode_game.snapshot()
    for _ in range(3):
        mode_clock[0]+=.1;mode_ui.set_pressed_mask(1);mode_ui.handle('UP');mode_ui.set_pressed_mask(0)
    assert not mode_ui.autoplay and mode_game.snapshot()==waiting
    for _ in range(3):
        mode_clock[0]+=.1;mode_ui.set_pressed_mask(1);mode_ui.handle('UP');mode_ui.set_pressed_mask(0)
    mode_ui.update(mode_clock[0]);mode_clock[0]+=100;mode_ui.update(mode_clock[0])
    assert mode_ui.manual_autoplay and mode_game.snapshot()==waiting
    mode_ui.handle('KEY1');assert not mode_ui.autoplay and mode_game.snapshot()==waiting
    mode_ui.close();assert not mode_advisor._thread.is_alive()
    quick_clock=[0.0]
    quick_ui=PokerUI(Session(rng=random.Random(25)),clock=lambda:quick_clock[0])
    quick_ui.speed=2;quick_ui.handle('DOWN');quick_ui.speed=0
    quick_ui.handle_sampled('DOWN',0.0)
    settled=quick_ui.session.snapshot()
    assert settled['phase']=='result' and quick_ui._animation['kind']=='draw'
    quick_ui.handle_sampled('DOWN',0.06)
    assert quick_ui.session.phase=='hold' and quick_ui._animation['kind']=='deal'
    assert quick_ui.session.credits==settled['credits']-settled['total_bet']
    assert quick_ui.session.active_multipliers==settled['multipliers']
    assert quick_ui.session.rounds==settled['rounds']
    next_deal=quick_ui.session.snapshot();quick_ui.handle('DOWN')
    assert quick_ui.session.snapshot()==next_deal and quick_ui._animation is None
    quick_ui.close()
    stage('strategy-functional-autoplay-complete')

    assert set(frames) == {'ready','hold','hint-on','manual-best-hold','autoplay','result','draw-hint','draw-hint-pulse','autoplay-manual','autoplay-manual-wait'}
    # Exercise all twelve delivered games, their actual asynchronous advisors,
    # menu selection, max wager, M pause, best holds and settlement in ARMv6.
    from poker_games import GAMES
    from poker_cabinet_strategy import GameStrategyTable,freeze_round
    cabinet_clock=[0.0]
    cabinet_ui=PokerUI(Session(game_id='bp3',cabinet_defaults=False,rng=random.Random(600)),
                      cabinet=True,clock=lambda:cabinet_clock[0])
    assert cabinet_ui.menu=={'page':'cabinet','index':0,'return':False}
    capture(cabinet_ui,'cabinet-menu')
    cabinet_checks=[]
    for game_index,game_spec in enumerate(GAMES):
        stage('cabinet-%s-before-select' % game_spec.id)
        cabinet_ui.menu={'page':'cabinet','index':game_index,'return':game_index>0}
        cabinet_ui.handle('CENTER')
        assert cabinet_ui.session.game.id==game_spec.id
        assert (cabinet_ui.session.bet_per_hand,cabinet_ui.session.num_hands)==(10,game_spec.hands)
        cabinet_ui.speed=2
        before_max=cabinet_ui.session.snapshot()
        cabinet_ui._button_action(3);cabinet_ui._button_action(4)
        assert cabinet_ui.session.snapshot()==before_max
        cabinet_ui.handle('DOWN')
        assert cabinet_ui.session.phase=='hold' and cabinet_ui.session.num_hands==game_spec.hands
        prepared_token=cabinet_ui._advisor_token
        assert prepared_token is not None,(game_spec.id,'missing first-deal preload')
        first_deal=cabinet_ui.session.snapshot()
        # The very first double tap must keep the original cold request alive
        # through both releases, then set best holds without a repeated gesture.
        for _ in range(2):
            cabinet_clock[0]+=.1
            cabinet_ui.set_pressed_mask(1);cabinet_ui.handle('UP');cabinet_ui.set_pressed_mask(0)
            assert cabinet_ui._advisor_token==prepared_token
        cabinet_clock[0]+=.5
        deadline=time.monotonic()+120
        while cabinet_ui._manual_hold_key is not None or cabinet_ui._manual_up_due is not None:
            assert time.monotonic()<deadline,(game_spec.id,'first double UP missed')
            cabinet_ui.update(cabinet_clock[0]);time.sleep(.005)
        first_mask=sum(1<<i for i,h in enumerate(cabinet_ui.session.held) if h)
        expected_first=GameStrategyTable(game_spec.id).advise(freeze_round(first_deal)[1:])['mask']
        assert first_mask==expected_first,(game_spec.id,first_mask,expected_first)
        assert cabinet_ui.session.credits==first_deal['credits'] and cabinet_ui.session.rounds==0
        assert not cabinet_ui.autoplay and not cabinet_ui.hint_visible
        # First held peek on that first hand must appear without changing holds.
        cabinet_clock[0]+=.5
        before_peek=cabinet_ui.session.snapshot()
        cabinet_ui.set_pressed_mask(1);cabinet_ui.handle('UP')
        cabinet_clock[0]+=.5
        deadline=time.monotonic()+120
        while not cabinet_ui.hint_visible:
            assert time.monotonic()<deadline,(game_spec.id,'first held hint missed')
            cabinet_ui.update(cabinet_clock[0]);time.sleep(.005)
        assert cabinet_ui._advice['mask']==expected_first
        assert cabinet_ui.session.snapshot()==before_peek
        cabinet_ui.set_pressed_mask(0)
        assert not cabinet_ui.hint_visible
        cabinet_clock[0]+=.5;cabinet_ui.update(cabinet_clock[0])
        for _ in range(3):
            cabinet_clock[0]+=.1
            cabinet_ui.set_pressed_mask(1);cabinet_ui.handle('UP');cabinet_ui.set_pressed_mask(0)
        assert cabinet_ui.manual_autoplay
        deadline=time.monotonic()+120
        while cabinet_ui._advice is None and time.monotonic()<deadline:
            cabinet_ui.update(cabinet_clock[0]);time.sleep(.005)
        assert cabinet_ui._advice is not None,(game_spec.id,'missing actual cabinet advice')
        expected_mask=cabinet_ui._advice['mask'];before=cabinet_ui.session.snapshot()
        cabinet_clock[0]+=1000;cabinet_ui.update(cabinet_clock[0])
        assert cabinet_ui.session.snapshot()==before
        cabinet_ui.handle('DOWN')
        result=cabinet_ui.session.snapshot()
        assert cabinet_ui.manual_autoplay and result['phase']=='result'
        assert result['held']==[bool(expected_mask&(1<<i)) for i in range(5)]
        assert len(result['results'])==game_spec.hands
        assert result['credits']==before['credits']+sum(x['payout'] for x in result['results'])
        capture(cabinet_ui,'cabinet-'+game_spec.id)
        cabinet_checks.append({'game_id':game_spec.id,'hands':game_spec.hands,
                               'deck_size':game_spec.deck_size,'mask':expected_mask,
                               'first_double_up_best_holds':True,'first_held_hint':True,
                               'rounds':result['rounds'],'status':'PASS'})
        cabinet_ui.handle('LEFT');assert not cabinet_ui.autoplay
    cabinet_ui.close()
    assert not cabinet_ui._advisor._thread.is_alive()
    report = {
        'status':'PASS','mode':'strategy-and-ui-functional-only',
        'python':sys.version,'pillow':PIL.__version__,'version':'0.5.1',
        'machine':os.uname().machine,'native_resolution':[320,240],
        'cabinet':{'status':'PASS','games':cabinet_checks,'menu_boot_checked':True,
                   'real_async_advice_all_twelve':True,'two_press_M_preserved':True,
                   'all_workers_joined':True},
        'strategy_and_autoplay':{
            'status':'PASS','known_cases':cases,'known_mask_cases':len(known),
            'multiplier_variation_cases':16,'autoplay_rounds':auto_game.rounds,
            'single_hint_mask':hint_mask,'hint_preserved_session':True,
            'held_up_hint_solid_red_until_release':True,
            'hint_hold_delay_seconds':PokerUI.HINT_HOLD_SECONDS,
            'hint_invisible_before_hold_delay_even_with_ready_advice':True,
            'release_removes_all_advice_pixels':True,
            'draw_five_real_advice_mask':0,
            'draw_five_only_actual_draw_button_flashes_red':True,
            'draw_hint_flash_cycle_seconds':PokerUI.HINT_DRAW_FLASH_SECONDS,
            'autoplay_normal_renderer_with_small_footer_a_only':True,
            'paced_autoplay_fake_clock_checks':pacing_checks,
            'autoplay_stage_timeline':timeline,
            'pacing_profiles':list(PokerUI.AUTO_PROFILES),
            'double_up_speed_cycle_keeps_hand_and_autoplay':speed_double_checks,
            'triple_up_toggles_both_directions_without_speed_change':True,
            'manual_double_up_sets_best_holds_without_draw_or_spend':True,
            'held_up_during_auto_does_not_change_speed':True,
            'medium_one_chevron_fast_two_chevrons':True,
            'small_filled_triangles_medium_left_fast_adds_right':True,
            'manual_pause_preserved_state':True,
            'three_captured_up_edges_060_apart_never_auto':True,
            'three_captured_up_edges_020_apart_with_100_dispatch_gap_activate':True,
            'stop_key_consumed_without_game_action':True,
            'fresh_down_during_draw_immediately_deals_next_hand_once':True,
            'fresh_down_during_deal_only_reveals_cards':True,
            'both_advisor_workers_joined':True,
            'manual_autoplay_real_advisor_cycles':2,
            'manual_autoplay_waits_without_debit_until_down':True,
            'manual_autoplay_two_down_presses_per_round':True,
            'manual_autoplay_waits_after_deal_before_holds_or_draw':True,
            'manual_autoplay_ready_advice_draw_without_pacing_or_animation':True,
            'manual_autoplay_default_first_mode':True,
            'manual_autoplay_m_native_size':[5,4],
            'manual_autoplay_marker':'A M beside speaker',
            'all_advisor_workers_joined':True,
            'table_sha256':hashlib.sha256(table.raw).hexdigest(),
            'bellman_span':table.certificate,
            'scope':'Actual delivered Python strategy, async advisor and UI in stock ARM emulation; fake presentation clock; fixture Random injection only'},
        'frames':frames,'autoplay_rounds_checked':3,
        'png_sha256':{name+'.png':hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest()
                      for name in sorted(frames)},
        'input_wall_clock_qualification':'NOT CLAIMED',
        'full_probe_timing_report_replaced':False,
        'full_probe_timing_report_scope':'Separate full probe results, including failures, remain authoritative for their wall-clock checks',
        'delivered_image_entrypoint_untouched':True,
        'diagnostic_entrypoint_replaced':True,
        'physical_display_tested':False,'physical_buttons_tested':False,
        'camera_or_signing_tested':False,'production_rng_path_tested':False,
        'duration_seconds':round(time.monotonic()-started,3)}
    (out/'arm-report.json').write_text(json.dumps(report,indent=2)+'\n')
    stage('strategy-functional-report-complete')
except BaseException:
    (out/'arm-error.txt').write_text(traceback.format_exc())
    raise
finally:
    if watcher_stop is not None:
        watcher_stop.set()
    if watcher_thread is not None:
        watcher_thread.join(timeout=2.0)
'''
