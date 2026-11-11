#!/usr/bin/env python3
"""Run the packaged poker code in the stock ARM kernel/rootfs under QEMU.

Only disposable regular-file images are written. The diagnostic /start.sh
replaces the production entrypoint in a separate probe CPIO; the delivered IMG
is not changed. GPIO/display/signing remain outside this emulated check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

GUEST = r'''import hashlib, json, os, random, statistics, sys, time, traceback
from pathlib import Path
sys.path.insert(0, '/opt/dino')
out = Path('/poker-proof')
def stage(name):
    (out/'arm-stage.txt').write_text(name+'\n')
    os.sync()
try:
    stage('python-entered')
    import PIL
    from PIL import Image
    from poker_engine import Session, RandomNotReady
    from poker_ui import PokerUI
    from hardware import PlusHardware, rgb565_bytes
    import launcher
    stage('imports-complete')
    # Read the production adapter with simulated physical BOARD pins, not a
    # duplicate of BUTTON_PINS. These literal expected masks encode the user's
    # standard pin layout independently of that tuple. Down is Deal / Draw;
    # both middle buttons Hold / Confirm and start the next hand from results.
    from types import SimpleNamespace
    mapping_owner = PlusHardware()
    pressed_pins = set()
    mapping_owner.gpio = SimpleNamespace(
        LOW=0, input=lambda pin: 0 if pin in pressed_pins else 1)
    physical_contract = {31:1, 35:2, 29:4, 37:8, 33:16, 40:32, 38:64, 36:128}
    mapping_results = []
    assert mapping_owner.read_mask() == 0
    for pin, expected_mask in physical_contract.items():
        pressed_pins.clear()
        pressed_pins.add(pin)
        actual_mask = mapping_owner.read_mask()
        assert actual_mask == expected_mask, (pin, actual_mask, expected_mask)
        mapping_results.append({'physical_board_pin':pin, 'logical_mask':actual_mask})
    pressed_pins.clear()
    pressed_pins.update((40,36))
    assert mapping_owner.read_mask() == launcher.SIGNER_CHORD
    pressed_pins.update((33,38))
    assert mapping_owner.read_mask() == launcher.SIGNER_CHORD | launcher.KEY2 | (1 << 4)
    pressed_pins.clear()
    physical_control_mapping = {
        'status':'PASS', 'pins_checked':mapping_results,
        'left_dpad_center':{'physical_board_pin':33, 'logical_action':'CENTER', 'role':'Hold / Confirm; next deal on results'},
        'right_middle':{'physical_board_pin':38, 'logical_action':'KEY2', 'role':'Hold / Confirm; next deal on results'},
        'dpad_down':{'physical_board_pin':35, 'logical_action':'DOWN', 'role':'Deal / Draw'},
        'dpad_up':{'physical_board_pin':31, 'logical_action':'UP', 'role':'Hint; double press toggles autoplay'},
        'outer_chord_board_pins':[40,36],
        'outer_chord_unchanged':True,
        'scope':'Production PlusHardware.read_mask with simulated GPIO levels in stock ARM Python; no physical GPIO exercised',
        'upstream_signer_button_mapping_modified':False,
    }
    stage('physical-control-mapping-complete')
    asset_path = Path('/opt/dino/assets/videopoker/manifest.json')
    asset_raw = asset_path.read_bytes()
    asset_manifest = json.loads(asset_raw)
    for asset in asset_manifest['assets']:
        path = Path(asset['path'])
        assert not path.is_absolute() and '..' not in path.parts
        body = (asset_path.parent/path).read_bytes()
        assert len(body)==asset['bytes'] and hashlib.sha256(body).hexdigest()==asset['sha256']
    asset_proof = {'manifest_sha256':hashlib.sha256(asset_raw).hexdigest(),
                   'asset_count':len(asset_manifest['assets']),
                   'asset_bytes':sum(asset['bytes'] for asset in asset_manifest['assets']),
                   'glyph_atlas_count':len(asset_manifest.get('glyph_atlases',{})),
                   'all_declared_asset_hashes_verified':True}
    started = time.monotonic()
    game = Session(rng=random.Random(20261110))
    ui_start = time.monotonic()
    ui = PokerUI(session=game)
    constructor_ms = (time.monotonic()-ui_start)*1000
    render_start = time.monotonic()
    first_frame = ui.render()
    first_render_ms = (time.monotonic()-render_start)*1000
    assert first_frame.size == (320,240) and first_frame.mode == 'RGB'
    first_frame.save(out/'ready.png')
    frame_render_ms = {}
    def capture(name):
        begin = time.monotonic()
        image = ui.render()
        frame_render_ms[name] = round((time.monotonic()-begin)*1000,3)
        assert image.size == (320,240) and image.mode == 'RGB'
        image.save(out/(name+'.png'))
    cached_render_ms = []
    packed_frame_ms = []
    for _ in range(12):
        begin = time.monotonic()
        cached = ui.render()
        cached_render_ms.append((time.monotonic()-begin)*1000)
        begin = time.monotonic()
        packed = rgb565_bytes(cached)
        packed_frame_ms.append((time.monotonic()-begin)*1000)
        assert len(packed) == 153600
    badge_render_ms = []
    for index in range(1,13):
        assert ui.update(ui._badge_started+index*.201)
        begin = time.monotonic()
        badge = ui.render()
        badge_render_ms.append((time.monotonic()-begin)*1000)
        assert badge.size==(320,240) and badge.mode=='RGB'
    ui.update(ui._badge_started)
    stage('ready-render-complete')
    game.deal()
    capture('deal')
    if game.phase == 'hold':
        game.toggle_hold(0)
        game.toggle_hold(2)
        game.draw()
    capture('result')
    assert len(game.hands) == len(game.results) == 10
    assert game.credits == 10000-100+game.total_win
    for hand in game.hands:
        assert len(hand) == len(set(hand)) == 5
        assert hand[0] == game.initial[0] and hand[2] == game.initial[2]
    game.set_feature(False)
    assert game.total_bet == 50
    for i in range(100):
        game.deal()
        if game.phase == 'hold': game.draw()
        if game.credits < game.total_bet: game.reset()
    # Low-wager active-hand selection is part of the classic ten-play cabinet.
    selected = Session(rng=random.Random(20261111))
    selected.set_bet_per_hand(1)
    selected.set_num_hands(3)
    assert selected.total_bet == 3
    selected.deal()
    if selected.phase == 'hold': selected.draw()
    assert len(selected.hands) == len(selected.results) == 3
    assert selected.credits == 10000-3+selected.total_win
    selected.set_bet_per_hand(5)
    assert selected.num_hands == 10 and selected.total_bet == 50
    stage('seeded-engine-cases-complete')
    # Exercise the actual default production path, not merely the RNG's type.
    entropy_environment = {'dev_hwrng_present':Path('/dev/hwrng').exists(),
                           'entropy_avail':None,'hw_random_kernel_flags':None}
    try:
        entropy_environment['entropy_avail'] = int(Path('/proc/sys/kernel/random/entropy_avail').read_text().strip())
    except (OSError,ValueError): pass
    if Path('/proc/config.gz').is_file():
        try:
            import gzip
            kernel_config = gzip.decompress(Path('/proc/config.gz').read_bytes()).decode()
            entropy_environment['hw_random_kernel_flags'] = [line for line in kernel_config.splitlines()
                if line.startswith('CONFIG_HW_RANDOM') or line.startswith('# CONFIG_HW_RANDOM')]
        except (ImportError,OSError,ValueError): pass
    production = Session()
    assert isinstance(production._rng, random.SystemRandom)
    production_before = production.snapshot()
    random_started = time.monotonic()
    random_cpu_started = time.process_time()
    try:
        production.deal()
    except RandomNotReady:
        assert production.snapshot()==production_before
        entropy_ready = False
        production_rng_result = 'WAIT_NONBLOCKING_WITH_FULL_STATE_UNCHANGED'
    else:
        entropy_ready = True
        production_rng_result = 'VALID_DEAL_USING_OS_RANDOM'
        assert len(production.initial)==len(set(production.initial))==5
        assert all(type(card) is int and 0<=card<52 for card in production.initial)
        assert production.phase in ('hold','result')
        assert production.credits==10000-100+production.total_win
    random_wall_ms = (time.monotonic()-random_started)*1000
    random_cpu_ms = (time.process_time()-random_cpu_started)*1000
    # Guest process CPU excludes host scheduling pauses. No physical latency
    # claim is made from the heavily loaded emulator's wall clock.
    if not entropy_ready: assert random_cpu_ms<1000
    stage('production-rng-path-complete')
    assert rgb565_bytes(Image.new('RGB',(1,1),'red')) == bytes((248,0))
    assert rgb565_bytes(Image.new('RGB',(1,1),'lime')) == bytes((7,224))
    assert rgb565_bytes(Image.new('RGB',(1,1),'blue')) == bytes((0,31))

    class SynchronousInput:
        """Virtual-clock harness; the separate case below uses real sampling."""
        def __init__(self, hardware, *, clock):
            self.hardware, self.clock = hardware, clock
            self.router = launcher.InputRouter()
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return self.router.update(self.clock(), self.hardware.read_mask())
        def read_timed(self):
            captured_at = self.clock()
            entered, actions = self.router.update(captured_at, self.hardware.read_mask())
            return entered, tuple((captured_at, action) for action in actions)
        def reset(self): self.router.reset()
        @property
        def gesture_pending(self):
            gate = self.router.gate
            return (gate.hold_started is not None or gate.latched or
                    self.router.suppress_until_neutral)
        @property
        def pressed_mask(self):
            return self.router.buttons.stable if self.router.buttons.armed else 0

    def runtime_case(name, trace, long_animation=False, production_session=False):
        timeline = [0.0]
        closed = [False]
        frames = [0]
        lcd_bytes = []
        lcd_cpu_ms = []
        calls = []
        runtime_game = Session() if production_session else Session(rng=random.Random(25))
        runtime_ui = PokerUI(session=runtime_game,clock=lambda:timeline[0])
        if long_animation: runtime_ui.SPEEDS = (2.0,2.0,0.0)
        owner = PlusHardware()
        class LCD:
            def show_image(self,image):
                lcd_bytes.append(len(rgb565_bytes(image)))
            def blit_buffer(self,data,x,y,w,h):
                assert 0<=x<320 and 0<=y<240 and x+w<=320 and y+h<=240
                assert len(data)==w*h*2
                lcd_bytes.append(len(data))
        owner.display = LCD()
        class FakeHardware:
            def __enter__(self): return self
            def __exit__(self,*args): closed[0] = True
            def read_mask(self): return trace(timeline[0])
            def present(self,image):
                assert image.size==(320,240) and image.mode=='RGB'
                begin = time.monotonic()
                owner.present(image)
                lcd_cpu_ms.append((time.monotonic()-begin)*1000)
                frames[0] += 1
            def show_message(self,*args):
                raise AssertionError('Unexpected game failure')
        def simulated_sleep(dt):
            timeline[0] += dt
            assert timeline[0] < 10, 'Runtime gesture was blocked'
        def signer_callback(argv):
            assert closed[0], 'Hardware must be released before signer startup'
            calls.append('signer')
        launcher.main(hardware_factory=FakeHardware,ui_factory=lambda:runtime_ui,
                      clock=lambda:timeline[0],sleep=simulated_sleep,
                      signer_runner=signer_callback,input_factory=SynchronousInput)
        assert calls==['signer'] and frames[0]>=2
        assert 'seedsigner.controller' not in sys.modules
        runtime_ui.render().save(out/(name+'.png'))
        result={'case':name,'input_handoff':'PASS','simulated_seconds':round(timeline[0],3),
                'frames_rendered':frames[0],'lcd_writes':len(lcd_bytes),
                'lcd_bytes_total':sum(lcd_bytes),
                'fullframe_equivalent_bytes':frames[0]*153600,
                'largest_write_bytes':max(lcd_bytes),
                'mean_present_elapsed_ms':round(statistics.mean(lcd_cpu_ms),3),
                'largest_write_theoretical_spi_ms':round(max(lcd_bytes)*8/25000000*1000,3)}
        stage('runtime-case-complete:'+name)
        return runtime_game,runtime_ui,result

    def play_trace(t):
        if .10<=t<.19 or .90<=t<.99 or 1.10<=t<1.80: return 1<<1
        if .60<=t<.69: return 1<<4
        if 2.0<=t<4.15: return launcher.SIGNER_CHORD
        return 0
    runtime_game,runtime_ui,play=runtime_case('animated-result',play_trace)
    assert runtime_game.rounds==1 and runtime_game.phase=='result'
    assert runtime_game.credits==10000-100+runtime_game.total_win
    assert runtime_ui._animation is None
    def animation_trace(t):
        if .10<=t<.19: return 1<<1
        if .20<=t<2.35: return launcher.SIGNER_CHORD
        return 0
    runtime_game,runtime_ui,animation=runtime_case('gesture-during-animation',animation_trace,True)
    assert runtime_game.rounds==0 and runtime_ui._animation is not None
    assert animation['simulated_seconds']<2.5
    def menu_trace(t):
        if .10<=t<.20: return launcher.KEY3
        if .40<=t<.50: return 1<<4
        if .80<=t<2.95: return launcher.SIGNER_CHORD
        return 0
    runtime_game,runtime_ui,menu=runtime_case('gesture-in-paytable',menu_trace)
    assert runtime_game.phase=='ready' and runtime_game.credits==10000
    assert runtime_ui.menu['page']=='paytable'
    def selected_trace(t):
        if .10<=t<.20 or 2.20<=t<2.30: return launcher.KEY3
        if any(start<=t<start+.09 for start in (.40,.60,.80,1.00)): return 1<<3
        if any(start<=t<start+.09 for start in (1.20,1.60,1.80,2.00)): return 1<<4
        if 1.40<=t<1.49: return 1<<2
        if 2.50<=t<2.59 or 3.10<=t<3.19: return 1<<1
        if 4.00<=t<6.15: return launcher.SIGNER_CHORD
        return 0
    runtime_game,runtime_ui,selected_case=runtime_case('selected-three-hands',selected_trace)
    assert runtime_game.num_hands==3 and runtime_game.bet_per_hand==1
    assert runtime_game.rounds==1 and len(runtime_game.results)==3
    assert runtime_game.credits==10000-3+runtime_game.total_win
    # Force the late-entropy condition for a whole production UI/input flow,
    # including retry and the hidden-entry gesture. This does not seed a deck.
    import poker_engine
    real_getrandom = poker_engine.os.getrandom
    def temporarily_unready(*args,**kwargs): raise BlockingIOError()
    def entropy_trace(t):
        if .10<=t<.19 or .40<=t<.49: return 1<<1
        if .80<=t<2.95: return launcher.SIGNER_CHORD
        return 0
    try:
        poker_engine.os.getrandom = temporarily_unready
        runtime_game,runtime_ui,waiting_case=runtime_case('entropy-wait-retry',entropy_trace,production_session=True)
    finally:
        poker_engine.os.getrandom = real_getrandom
    assert runtime_game.phase=='ready' and runtime_game.credits==10000 and runtime_game.rounds==0
    assert runtime_ui.notice is not None and not runtime_ui._credit_notice

    # Unlike the virtual-clock cases, this uses the actual worker and wall-clock
    # scheduling. The first tap begins and ends inside a blocked LCD present.
    # Previously that tap disappeared because presenting and polling were serial.
    threaded_started = [None]
    threaded_closed = [False]
    threaded_frames = [0]
    threaded_actions = []
    threaded_streams = []
    threaded_deadline = [None]
    threaded_game = Session(rng=random.Random(25))
    class ObservedUI(PokerUI):
        def handle(self, action):
            threaded_actions.append((time.monotonic(), action))
            return super().handle(action)
        def render(self):
            try: return super().render()
            except Exception:
                (out/'arm-threaded-render-error.txt').write_text(traceback.format_exc())
                raise
    threaded_ui = ObservedUI(session=threaded_game)
    threaded_ui.SPEEDS = (2.0,2.0,0.0)
    class BlockingLCDHardware:
        def __enter__(self): return self
        def __exit__(self,*args):
            assert threaded_streams and not threaded_streams[0].running
            threaded_closed[0] = True
        def read_mask(self):
            assert not threaded_closed[0], 'Input thread survived GPIO cleanup'
            if threaded_started[0] is None: return 0
            elapsed = time.monotonic()-threaded_started[0]
            if .120<=elapsed<.155 or .450<=elapsed<.950: return 1<<1
            if 1.100<=elapsed<3.250: return launcher.SIGNER_CHORD
            return 0
        def present(self, image):
            assert image.size==(320,240) and image.mode=='RGB'
            threaded_frames[0] += 1
            if threaded_started[0] is None:
                threaded_started[0] = time.monotonic()
                # Bound the physical-input experiment from its first visible
                # frame, not from PNG/font loading before the input service.
                threaded_deadline[0] = threaded_started[0] + 7.0
                time.sleep(.240)
        def show_message(self,*args): raise AssertionError('Threaded input game failed')
    def real_input_factory(hardware, *, clock):
        stream = launcher.SampledInput(hardware,clock=clock)
        threaded_streams.append(stream)
        return stream
    threaded_calls = []
    def threaded_signer(argv):
        assert threaded_closed[0] and not threaded_streams[0].running
        threaded_calls.append('signer')
    def threaded_sleep(duration):
        if time.monotonic()>threaded_deadline[0]:
            diagnostics={'sampler_stats':threaded_streams[0].stats,
                         'first_present_started':threaded_started[0],
                         'actions':[(round(at-(threaded_started[0] or 0),3),action)
                                    for at,action in threaded_actions],
                         'phase':threaded_game.phase,'frames':threaded_frames[0]}
            (out/'arm-threaded-debug.json').write_text(json.dumps(diagnostics,indent=2)+'\n')
            raise AssertionError('Threaded input did not finish explicit gesture: '+repr(diagnostics))
        time.sleep(duration)
    stage('threaded-input-starting')
    # A separate initial-render guard also bounds failed UI startup, without
    # spending the seven-second gesture budget on pre-experiment rendering.
    threaded_deadline[0] = time.monotonic()+30.0
    launcher.main(hardware_factory=BlockingLCDHardware,ui_factory=lambda:threaded_ui,
                  input_factory=real_input_factory,signer_runner=threaded_signer,
                  sleep=threaded_sleep)
    assert threaded_calls==['signer']
    assert [action for _,action in threaded_actions]==['DOWN','DOWN'], threaded_actions
    assert threaded_game.phase=='hold' and threaded_game.rounds==0
    assert threaded_game.credits==9900 and threaded_ui._animation is None
    first_action_ms=(threaded_actions[0][0]-threaded_started[0])*1000
    assert first_action_ms>=240, 'The first tap must occur during the blocked present'
    threaded_ui.render().save(out/'threaded-input.png')
    threaded_result = {
        'status':'PASS','production_sampled_input_used':True,
        'blocked_present_seconds':.240,'tap_seconds':.035,
        'tap_window_inside_present_seconds':[.120,.155],
        'held_key_seconds':.500,'ordinary_actions':['DOWN','DOWN'],
        'first_action_dispatch_ms_from_present_start':round(first_action_ms,3),
        'ending_phase':threaded_game.phase,'ending_credits':threaded_game.credits,
        'settled_rounds':threaded_game.rounds,
        'held_key_did_not_repeat':True,'rendered_frames':threaded_frames[0],
        'sampler_stopped_before_gpio_cleanup':True,
        'sampler_stats':threaded_streams[0].stats,
        'scope':'Real wall-clock sampling and blocked simulated LCD in ARM QEMU; no physical GPIO or button-latency measurement'}
    threaded_result['deadline_anchor'] = 'Seven seconds after first present; separate30s initial-render guard'
    # Exercise Pillow's GIL behavior too: keep recompositing an actual board and
    # run the real changed-pixel/RGB565 path rather than merely sleeping in SPI.
    cpu_started = [None]
    cpu_closed = [False]
    cpu_reads = [0]
    cpu_writes = [0]
    class CPULoadHardware:
        def read_mask(self):
            assert not cpu_closed[0], 'CPU-load sampler survived cleanup'
            cpu_reads[0] += 1
            if cpu_started[0] is None: return 0
            elapsed = time.monotonic()-cpu_started[0]
            return 1<<1 if .120<=elapsed<.160 else 0
    class CPULoadLCD:
        def show_image(self, image):
            assert len(rgb565_bytes(image))==153600
            cpu_writes[0] += 1
        def blit_buffer(self, data, x, y, width, height):
            assert len(data)==width*height*2
            cpu_writes[0] += 1
    cpu_owner = PlusHardware()
    cpu_owner.display = CPULoadLCD()
    cpu_frames = 0
    with launcher.SampledInput(CPULoadHardware()) as cpu_stream:
        cpu_started[0] = time.monotonic()
        while time.monotonic()-cpu_started[0]<.300:
            # Real hold changes invalidate even a focus-independent board cache.
            # This exercises full composition, not merely a cached focus overlay.
            threaded_game.toggle_hold(cpu_frames%5)
            cpu_owner.present(threaded_ui.render())
            cpu_frames += 1
        cpu_entered,cpu_actions = cpu_stream.read()
        assert not cpu_entered and cpu_actions==('DOWN',), cpu_actions
        cpu_stats = cpu_stream.stats
    assert not cpu_stream.running
    cpu_closed[0] = True
    closed_read_count = cpu_reads[0]
    time.sleep(.020)
    assert cpu_reads[0]==closed_read_count
    threaded_result['continuous_pillow_rgb565_work'] = {
        'status':'PASS','tap_seconds':.040,
        'tap_window_seconds':[.120,.160],'minimum_render_work_seconds':.300,
        'full_board_cache_invalidated_by':'Session.toggle_hold on each frame',
        'rendered_frames':cpu_frames,'lcd_writes':cpu_writes[0],
        'captured_actions':list(cpu_actions),'sampler_stats':cpu_stats,
        'sampler_stopped_before_cleanup':True}
    stage('threaded-input-complete')
    # Exercise the delivered probability table, background advisor and actual
    # autoplay controller in stock ARM Python, without GPIO or future-RNG access.
    from poker_strategy import StrategyAdvisor, StrategyTable, _round
    strategy_start = time.monotonic()
    strategy_table = StrategyTable()
    strategy_cases = []
    strategy_game = Session(rng=random.Random(1))
    strategy_game.deal()
    for cards, expected in (((12,25,38,1,2),7), ((0,1,2,3,17),31),
                            ((11,24,37,50,12),31), ((0,15,30,44,12),16)):
        strategy_game.initial = list(cards)
        begin = time.monotonic()
        answer = strategy_table.advise(_round(strategy_game.snapshot()))
        assert answer['mask'] == expected, (cards,answer)
        strategy_cases.append({'cards':list(cards),'mask':answer['mask'],
                               'milliseconds':round((time.monotonic()-begin)*1000,3)})
    auto_clock = [0.70]
    auto_game = Session(rng=random.Random(250))
    auto_advisor = StrategyAdvisor()
    auto_ui = PokerUI(session=auto_game, clock=lambda:auto_clock[0], advisor=auto_advisor)
    auto_ui.speed = 2
    auto_ui.handle_sampled('UP', 0.0)
    auto_ui.handle_sampled('UP', .60)
    assert not auto_ui.autoplay and auto_game.credits == 10000
    auto_ui.pause_autoplay()
    auto_clock[0] = 1.0
    auto_ui.handle_sampled('UP', .90)
    auto_clock[0] = 2.0
    auto_ui.handle_sampled('UP', 1.10)
    assert auto_ui.autoplay
    auto_deadline = time.monotonic()+120
    while auto_game.rounds < 3 and time.monotonic()<auto_deadline:
        auto_clock[0] += .05
        auto_ui.update(auto_clock[0])
        time.sleep(.001)
    assert auto_game.rounds >= 3 and auto_ui.autoplay, auto_game.snapshot()
    auto_ui.pause_autoplay()
    paused = auto_game.snapshot()
    auto_clock[0] += 100
    auto_ui.update(auto_clock[0])
    assert auto_game.snapshot() == paused and not auto_ui.autoplay
    auto_ui.close()
    assert not auto_advisor._thread.is_alive()
    strategy_result = {'status':'PASS','cases':strategy_cases,
        'autoplay_rounds':auto_game.rounds,'manual_pause_preserved_state':True,
        'up_double_tap_uses_captured_edge_time':True,
        'worker_stopped_before_signer_boundary':True,
        'bellman_span':strategy_table.certificate,
        'table_sha256':hashlib.sha256(strategy_table.raw).hexdigest(),
        'scope':'Actual delivered Python strategy and UI in emulation; no physical Pi timing claim',
        'total_emulated_seconds':round(time.monotonic()-strategy_start,3)}
    stage('strategy-autoplay-complete')
    report={'status':'PASS','python':sys.version,'pillow':PIL.__version__,
            'version':'0.4.0','visual_assets':asset_proof,
            'physical_control_mapping':physical_control_mapping,
            'machine':os.uname().machine,'rounds_checked':107,
            'engine_rounds_checked':102,'runtime_rounds_checked':2,
            'autoplay_rounds_checked':3,
            'input_game_render_handoff_simulation':'PASS',
            'active_hands_selection':'PASS','animation_skip_double_spend':'PASS',
            'gesture_during_animation_and_menu':'PASS','rgb565_primary_colors':'PASS',
            'os_entropy_ready_in_guest':entropy_ready,
            'entropy_environment':entropy_environment,
            'production_rng_path_tested':production_rng_result,
            'production_rng_check_wall_ms':round(random_wall_ms,3),
            'production_rng_check_process_cpu_ms':round(random_cpu_ms,3),
            'entropy_wait_retry_gesture':'PASS',
            'runtime_cases':[play,animation,menu,selected_case,waiting_case],
            'threaded_input_regression':threaded_result,
            'strategy_and_autoplay':strategy_result,
            'performance':{'ui_constructor_ms':round(constructor_ms,3),
                           'first_render_ms':round(first_render_ms,3),
                           'first_deal_and_result_render_ms':frame_render_ms,
                           'cached_render_ms_median':round(statistics.median(cached_render_ms),3),
                           'cached_render_ms_max':round(max(cached_render_ms),3),
                           'badge_only_render_ms_median':round(statistics.median(badge_render_ms),3),
                           'badge_only_render_ms_max':round(max(badge_render_ms),3),
                           'fullframe_rgb565_ms_median':round(statistics.median(packed_frame_ms),3),
                           'scope':'Elapsed times in the stock ARM guest under QEMU, including host scheduling; simulated LCD, no physical SPI; not physical Pi speed or FPS measurements'},
            'duration_seconds':round(time.monotonic()-started,3),
            'native_resolution':[320,240],
            'delivered_image_entrypoint_untouched':True,
            'diagnostic_entrypoint_replaced':True,
            'physical_display_tested':False,'physical_buttons_tested':False,
            'camera_or_signing_tested':False}
    report['png_sha256'] = {path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(out.glob('*.png'))}
    (out/'arm-report.json').write_text(json.dumps(report,indent=2)+'\n')
except BaseException:
    (out/'arm-error.txt').write_text(traceback.format_exc())
    raise
'''

START = b'''#!/bin/sh
mkdir -p /poker-proof
count=0
while [ ! -b /dev/mmcblk0p1 ] && [ ! -b /dev/mmcblk1p1 ] && [ "$count" -lt 40 ]; do
    /sbin/mdev -s
    sleep 1
    count=$((count + 1))
done
device=/dev/mmcblk0p1
[ -b "$device" ] || device=/dev/mmcblk1p1
mount -t vfat "$device" /poker-proof || exit 1
uname -a > /poker-proof/arm-uname.txt
echo DIAGNOSTIC_ENTRYPOINT_REACHED > /poker-proof/arm-stage.txt
sync
/usr/bin/python3 -B /opt/dino/arm_probe.py > /poker-proof/arm-log.txt 2>&1
echo $? > /poker-proof/arm-exit.txt
sync
echo POKER_ARM_PROBE_FINISHED > /poker-proof/arm-done.txt
sync
umount /poker-proof
poweroff -f
'''


def main():
    from build_poker_image import Fat16, inspect_newc, pack_newc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--strategy-only', action='store_true',
                        help='Focused strategy/UI check; does not qualify wall-clock GPIO timing')
    parser.add_argument('--instruction-clock', action='store_true',
                        help='Use virtual instruction time for functional-only emulation, never physical timing')
    args = parser.parse_args()
    if args.instruction_clock and not args.strategy_only:
        parser.error('--instruction-clock is restricted to the functional-only probe')
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    original = args.image.read_bytes()
    fat = Fat16(original)
    overlays = [n for n in fat.files if n.endswith('.cpio')]
    if len(overlays) != 1:
        raise ValueError('Expected exactly one production external overlay')
    entries = inspect_newc(fat.files[overlays[0]])
    records = {name:(entry['mode'], entry['content']) for name,entry in entries.items()}
    records['start.sh'] = (stat.S_IFREG|0o755, START)
    probe_guest = GUEST
    if args.strategy_only:
        from arm_strategy_probe import GUEST as strategy_guest
        probe_guest = strategy_guest
    records['opt/dino/arm_probe.py'] = (stat.S_IFREG|0o644, probe_guest.encode())
    (folder/'probe.cpio').write_bytes(pack_newc(records))
    (folder/'zImage').write_bytes(fat.files['zImage'])
    dtb = folder/'qemu-only-pi-zero.dtb'
    dtb.write_bytes(fat.files['bcm2708-rpi-zero.dtb'])
    # The emulated Pi lacks these physical peripherals. These changes affect
    # only the diagnostic DTB, never the delivered image or its firmware files.
    dtb_changes = {'/soc/watchdog@7e100000':'disabled',
                   '/soc/mmc@7e300000':'okay', '/soc/fb':'disabled',
                   '/soc/mailbox@7e00b840':'disabled'}
    for node,status in dtb_changes.items():
        subprocess.run(['fdtput','-t','s',str(dtb),node,'status',status],check=True)
    sd = folder/'probe-sd.img'
    sd.write_bytes(original)
    with sd.open('r+b') as f: f.truncate(64*1024*1024)
    command = ['qemu-system-arm','-M','raspi0','-m','512M',
               '-kernel',str(folder/'zImage'),'-dtb',str(dtb),
               '-initrd',str(folder/'probe.cpio'),'-append','console=ttyAMA0,115200 earlyprintk loglevel=7',
               '-drive','file='+str(sd)+',format=raw,if=sd',
               '-nographic','-monitor','none','-nic','none','-no-reboot']
    if args.instruction_clock:
        command += ['-accel','tcg,thread=single','-icount','shift=0,sleep=off']
    with (folder/'qemu.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + args.timeout
        try:
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(1)
                # Read only the small marker through FAT metadata. Re-parsing
                # all 64MiB plus the embedded kernel every second can compete
                # with QEMU on a loaded host and says nothing about device speed.
                # Earlier report/PNG writes are synced before this marker.
                try:
                    marker = subprocess.run(
                        ['mtype','-i',str(sd)+'@@'+str(fat.offset),'::arm-done.txt'],
                        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5)
                    if marker.returncode == 0 and marker.stdout.startswith(b'POKER_ARM_PROBE_FINISHED'):
                        break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    guest = Fat16(sd.read_bytes()[:len(original)])
    for name,body in guest.files.items():
        if name.startswith('arm-') or name.endswith('.png'):
            (folder/name).write_bytes(body)
    code = guest.files.get('arm-exit.txt',b'missing').strip()
    if code != b'0' or 'arm-report.json' not in guest.files:
        raise RuntimeError('Guest probe failed: '+str(code)+': '+
                           guest.files.get('arm-log.txt',b'').decode(errors='replace'))
    report = json.loads(guest.files['arm-report.json'])
    for name,digest in report.get('png_sha256',{}).items():
        if Path(name).name != name or not name.endswith('.png'):
            raise ValueError('Unsafe guest PNG name')
        body = guest.files[name]
        if (hashlib.sha256(body).hexdigest() != digest
                or body[:8] != b'\x89PNG\r\n\x1a\n'
                or struct.unpack('>II',body[16:24]) != (320,240)
                or not body.endswith(b'IEND\xaeB`\x82')):
            raise ValueError('Guest PNG readback failed: '+name)
    report['guest_png_readback_verified'] = bool(report.get('png_sha256'))
    report.update({'qemu_only_dtb_changes':dtb_changes,
                   'probe_mode':'strategy-and-ui-functional-only' if args.strategy_only else 'full-including-realtime-input',
                   'diagnostic_clock':'virtual-instruction-clock; no wall-clock qualification' if args.instruction_clock else 'default QEMU clock',
                   'production_dtb_modified':False,
                   'production_image_sha256':hashlib.sha256(original).hexdigest(),
                   'qemu_only_dtb_sha256':hashlib.sha256(dtb.read_bytes()).hexdigest(),
                   'qemu_termination':'Stopped after completed guest marker or bounded timeout',
                   'marker_polling':'Lightweight mtools mtype; full FAT decode only after completion',
                   'guest_sync_before_done_marker':True,
                   'gpu_bootloader_tested':False})
    (folder/'arm-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
