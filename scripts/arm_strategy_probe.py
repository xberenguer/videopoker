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
        state['_speed'] = ui.speed
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
        assert bounds is not None and bounds[0]>=4 and bounds[1]>=10 and bounds[2]<=17 and bounds[3]<=24
        assert (255,255,0) in set(image.crop((4,10,17,24)).getdata())
        image.paste(normal.crop((4,10,17,24)), (4,10))
        assert image.tobytes() == normal.tobytes(), 'Only the small A may differ during autoplay'

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
    assert manual_ui._advice is not None and manual_ui.hint_visible
    assert manual_game.snapshot() == before_hint, 'A hint must not alter held cards or game state'
    capture(manual_ui,'hint-on')
    hint_mask = manual_ui._advice['mask']
    assert hint_mask != 0, 'Fixture must visibly recommend at least one held card'
    assert manual_ui.render().tobytes() != plain_render(manual_ui).tobytes()
    # Held UP remains solid red across presentation time; release removes all
    # advice rendering and pending/results without changing the poker session.
    manual_clock[0] += 2.0
    manual_ui.update(manual_clock[0])
    assert manual_ui.hint_visible
    assert manual_ui.render().tobytes() != plain_render(manual_ui).tobytes()
    assert manual_game.snapshot() == before_hint
    manual_ui.set_pressed_mask(0)
    manual_ui.update(manual_clock[0])
    assert not manual_ui.hint_visible
    assert manual_ui._advisor_token is None and manual_ui._advice is None
    assert manual_ui.render().tobytes() == plain_render(manual_ui).tobytes()
    assert manual_game.snapshot() == before_hint
    manual_ui.close()
    assert not manual_advisor._thread.is_alive()
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
    assert auto_ui.autoplay
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
            assert auto_clock[0]-consider_started >= 6.0-1e-7
            pacing_checks['consider'] += 1
        if current_stage == 'draw' and previous_stage != 'draw':
            draw_started = auto_clock[0]
        if phase == 'result' and previous['phase'] == 'hold':
            assert draw_started is not None
            assert auto_clock[0]-draw_started >= 2.0-1e-7
            pacing_checks['draw'] += 1
        if current_stage == 'result' and previous_stage != 'result':
            result_started = auto_clock[0]
        if phase == 'hold' and previous['phase'] == 'result':
            assert result_started is not None
            assert auto_clock[0]-result_started >= 4.0-1e-7
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
    assert auto_ui.AUTO_CONSIDER_SECONDS == 6.0
    assert auto_ui.AUTO_SELECT_SECONDS == .65
    assert auto_ui.AUTO_HOLD_SECONDS == 2.0
    assert auto_ui.AUTO_RESULT_SECONDS == 4.0
    paused = auto_game.snapshot()
    selected = auto_ui.selected_card
    auto_ui.handle('LEFT')
    assert not auto_ui.autoplay and auto_ui.selected_card == selected
    assert auto_ui.render().tobytes() == plain_render(auto_ui).tobytes()
    auto_clock[0] += 100
    auto_ui.update(auto_clock[0])
    assert auto_game.snapshot() == paused and not auto_ui.autoplay
    auto_ui.close()
    assert not auto_advisor._thread.is_alive()
    stage('strategy-functional-autoplay-complete')

    assert set(frames) == {'ready','hold','hint-on','autoplay','result'}
    report = {
        'status':'PASS','mode':'strategy-and-ui-functional-only',
        'python':sys.version,'pillow':PIL.__version__,'version':'0.4.1',
        'machine':os.uname().machine,'native_resolution':[320,240],
        'strategy_and_autoplay':{
            'status':'PASS','known_cases':cases,'known_mask_cases':len(known),
            'multiplier_variation_cases':16,'autoplay_rounds':auto_game.rounds,
            'single_hint_mask':hint_mask,'hint_preserved_session':True,
            'held_up_hint_solid_red_until_release':True,
            'release_removes_all_advice_pixels':True,
            'autoplay_normal_renderer_with_small_top_left_a_only':True,
            'paced_autoplay_fake_clock_checks':pacing_checks,
            'autoplay_stage_timeline':timeline,
            'pacing_seconds':{'consider':6.0,'per_card_selection':.65,'before_draw':2.0,'result':4.0},
            'manual_pause_preserved_state':True,
            'three_captured_up_edges_060_apart_never_auto':True,
            'three_captured_up_edges_020_apart_with_100_dispatch_gap_activate':True,
            'stop_key_consumed_without_game_action':True,
            'both_advisor_workers_joined':True,
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
