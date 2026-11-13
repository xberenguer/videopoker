"""Real delivered trainer in stock ARMv6 rootfs, with diagnostic clock/RNG only."""
GUEST = r'''import hashlib,json,os,random,sys,time,traceback
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/dino')
out=Path('/poker-proof')
def stage(name):
    (out/'arm-stage.txt').write_text(name+'\n');os.sync()
try:
    stage('training-imports')
    from poker_app import PokerApp
    from poker_ui import PokerUI
    from poker_engine import Session
    from poker_games import GAMES
    from poker_training import TrainingState,DetailedTable
    from poker_training_store import Journal,TrainingStore,OFFSET,HEADER_BYTES,hardware_journal
    from poker_cabinet_strategy import freeze_round
    import platform
    class Clock:
        def __init__(self):self.now=0.0
        def __call__(self):return self.now
    checks=[];frames={};started=time.monotonic()
    table=DetailedTable()
    for game in sorted(GAMES,key=lambda g:g.id!='ddb10'):
        stage('training-'+game.id)
        clock=Clock();ui=PokerUI(Session(game_id=game.id,rng=random.Random(8841)),cabinet=True,clock=clock)
        app=PokerApp(play=ui,training_state=TrainingState(clock=clock),training_mode=True);t=app.trainer
        t.settings['mode']='test';ui.menu=None;ui.session.deal()
        deadline=time.monotonic()+90
        while t._token is not None and time.monotonic()<deadline:
            t.update(clock());time.sleep(.001)
        assert t.report is not None,game.id
        assert len(t.report['holds'])==32 and all(v['value']==v['value'] for v in t.report['holds'])
        bad=min(t.report['holds'],key=lambda v:v['value'])['mask']
        ui.session.held=[bool(bad&(1<<i)) for i in range(5)]
        before=ui.session.snapshot();rng=ui.session._rng.getstate()
        ui._play();assert t.page is None and t.inline_warning is not None,game.id
        assert ui.session.snapshot()==before and ui.session._rng.getstate()==rng
        if game.id=='ddb10':
            app.render().save(out/'training-inline-warning.png');frames['training-inline-warning']=True
            for page,name in [('ev','training-ev'),('ev_detail','training-ev-detail')]:
                t.page=page;t.index=0;app.render().save(out/(name+'.png'));frames[name]=True
            t.page=None
        ui.session.held=[bool(t.report['mask']&(1<<i)) for i in range(5)]
        ui._play()
        assert ui.session.phase=='result' and t.state.totals(game.id)['errors']==1
        assert t.state.totals(game.id)['corrected']==1
        assert len(t.state.errors(game.id))==1
        if game.id=='ddb10':
            for page,name in [('stats','training-stats'),('errors','training-errors'),('settings','training-options')]:
                t.page=page;t.index=0;app.render().save(out/(name+'.png'));frames[name]=True
        # Replay the original cards and per-hand multipliers through real deal.
        error=t.state.errors(game.id)[0]
        t.page=None;t._forced_error=error
        ui.session.deal()
        assert ui.session.initial==error['cards'] and ui.session.active_multipliers==error['multipliers']
        deadline=time.monotonic()+90
        while t._token is not None and time.monotonic()<deadline:t.update(clock());time.sleep(.001)
        assert t.report
        ui.session.held=[bool(t.report['mask']&(1<<i)) for i in range(5)]
        ui.session.draw();assert error['learned']
        # Actual automatic deal/hold/draw path, not a preselected fixture mask.
        ui._finish_animation();t.page=None;t.settings['mode']='test'
        # Earlier fixture calls bypassed PokerUI.handle, which clears notices.
        # Start from the same clean state as a real successful button action.
        ui._clear_notice()
        personal_before=tuple(t.state.totals(game.id)[k] for k in ('decisions','correct','errors'))
        ui.autoplay=True;ui.autoplay_speed=2;ui._auto_stage='deal';ui._auto_due=clock()
        target=ui.session.rounds+1;deadline=time.monotonic()+90
        while ui.session.rounds<target and time.monotonic()<deadline:
            clock.now+=.08;app.update(clock());time.sleep(.001)
            assert ui.autoplay,(game.id,ui.notice)
        assert ui.session.rounds==target,game.id
        ui.pause_autoplay();deadline=time.monotonic()+90
        while t.state.totals(game.id)['auto_checked']<1 and time.monotonic()<deadline:
            t.update(clock());time.sleep(.001)
        automatic=t.state.totals(game.id)
        assert (automatic['auto_decisions'],automatic['auto_checked'],automatic['auto_correct'])==(1,1,1),(game.id,automatic)
        assert automatic['auto_errors']==0 and automatic['auto_ev_lost']==0
        assert automatic['auto_wagered']==10*game.hands and automatic['auto_hands']==game.hands
        assert tuple(automatic[k] for k in ('decisions','correct','errors'))==personal_before
        if game.id=='ddb10':
            t.page='stats';t.stats_scope=2
            app.render().save(out/'autoplay-session-stats.png');frames['autoplay-session-stats']=True
            t.page=None
        if game.id in ('ddb3','job5','ddb10'):
            t.settings['mode']='coach';ui.session.deal()
            deadline=time.monotonic()+90
            while t._token is not None and time.monotonic()<deadline:t.update(clock());time.sleep(.001)
            ui._finish_animation()
            for tab,label in enumerate(('advice','ev','stats')):
                app.training_hud.tab=tab
                name='live-'+game.id+'-'+label
                app.render().save(out/(name+'.png'));frames[name]=True
        if game.id=='ddb10':
            # Single held UP peeks in M without applying holds or drawing.
            ui._clear_notice();ui.autoplay=True;ui.autoplay_speed=0;ui._auto_stage='manual-draw'
            ui._request_hint(clock(),prepare=True)
            before_peek=ui.session.snapshot()
            ui.set_pressed_mask(1,clock());ui.handle('UP');clock.now+=.31
            deadline=time.monotonic()+90
            while not ui.hint_visible and time.monotonic()<deadline:
                app.update(clock());clock.now+=.01;time.sleep(.001)
            assert ui.hint_visible and ui.manual_autoplay
            assert ui.session.snapshot()==before_peek
            app.training_hud.tab=0;app.render().save(out/'AM-red-peek.png');frames['AM-red-peek']=True
            ui.set_pressed_mask(0,clock());assert not ui.hint_visible
            assert ui.manual_autoplay and ui.session.snapshot()==before_peek
            ui.pause_autoplay()
        checks.append({'game':game.id,'full_32_holds':True,'warning_preserves_rng':True,'corrected_error_recorded_once':True,'replay_original_context':True,'learned':True,'actual_autoplay_round_scored':True,'autoplay_does_not_inflate_manual_accuracy':True})
        app.close()
    stage('training-RAM-only')
    import poker_training_store as storage
    original_discovery=storage.hardware_journal
    storage.hardware_journal=lambda:None
    try:
        memory_store=TrainingStore.hardware()
        assert memory_store.journal is None and memory_store._thread is None
        memory_state=TrainingState(memory_store);memory_state.begin('ddb10')
        memory_state.settings('ddb10')['mode']='coach'
        memory_state.totals('ddb10')['auto_correct']=7;memory_state.save()
        assert memory_store.status=='RAM only';memory_store.close()
        fresh=TrainingState(TrainingStore.hardware())
        assert not fresh.data['settings'] and not fresh.data['totals'] and not fresh.data['sessions']
        fresh.store.close()
    finally:storage.hardware_journal=original_discovery
    # Boot default is the actual integrated calculator/trainer entrypoint.
    clock=Clock();app=PokerApp(play=PokerUI(Session(rng=random.Random(2)),clock=clock),training_state=TrainingState(clock=clock))
    assert not app.training_mode and app.render().crop((0,0,320,220)).tobytes()==app.play.render().crop((0,0,320,220)).tobytes()
    app.set_pressed_mask_sampled(128,0);clock.now=1.1;app.update(clock());assert not app.trainer.active
    app.toggle_hidden_mode();assert app.training_mode and not app.trainer.active
    app.set_pressed_mask_sampled(128,0);clock.now=1.1;app.update(clock());assert app.trainer.active
    app.set_pressed_mask_sampled(0,1.2);app.handle_sampled('KEY3',1.2);assert app.trainer.active
    app.toggle_calculator();assert app.calculator_active and not app.trainer.active
    app.toggle_hidden_mode();assert not app.calculator_active and app.training_mode
    app.toggle_hidden_mode();assert not app.training_mode
    assert app.render().tobytes()==app.play.render().tobytes()
    app.close()
    report={'schema':1,'version':'0.6.6','status':'PASS','platform':platform.machine(),'python':platform.python_version(),
            'training_games':checks,'production_RAM_only':True,'new_state_has_no_history':True,'SD_history_requires_explicit_opt_in':True,
            'long_press_release_consumed':True,'normal_mode_unmarked':True,'hidden_trainer_gate':True,'calculator_utility_retained':True,'AM_held_peek_verified':True,
            'png_sha256':{name+'.png':hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest() for name in frames},
            'duration_seconds':round(time.monotonic()-started,3),'physical_hardware_tested':False,
            'scope':'Stock ARMv6 kernel/rootfs and actual delivered Python/UI/RAM history; fixture RNG and virtual presentation clock; GPIO/LCD simulated'}
    (out/'arm-report.json').write_text(json.dumps(report,indent=2)+'\n');stage('training-complete')
except BaseException:
    (out/'arm-error.txt').write_text(traceback.format_exc());raise
'''
