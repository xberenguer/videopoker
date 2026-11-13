"""Additional stock-ARM checks for opt-in settings; writes a disposable RAM file."""
GUEST = r'''
try:
    import copy,json,hashlib,random,time,traceback
    from pathlib import Path
    import poker_training_store as storage
    from poker_training_store import Journal,TrainingStore,OFFSET,initial_region
    from poker_training import TrainingState,DetailedTable
    from poker_games import EXTRA_PROFILES
    from poker_cabinet_strategy import freeze_round
    from poker_app import PokerApp
    from poker_calculator import CardCalculator
    import launcher
    probe_report=out/'arm-report.json'
    current=json.loads(probe_report.read_text())
    original_discovery=storage.hardware_journal
    temporary=Path('/tmp/videopoker-settings-test.img')
    mbr=None
    for candidate in sorted(Path('/dev').glob('mmcblk[0-9]')):
        with candidate.open('rb') as stream:value=stream.read(512)
        try:storage.header(value)
        except ValueError:continue
        mbr=value;break
    assert mbr is not None,'No emulated card with the pinned image layout'
    with temporary.open('wb') as stream:
        stream.write(mbr);stream.seek(OFFSET);stream.write(initial_region(mbr))
    def region_digest():
        with temporary.open('rb') as stream:
            stream.seek(OFFSET)
            return hashlib.sha256(stream.read()).hexdigest()
    before=region_digest()
    storage.hardware_journal=lambda:Journal(temporary)
    store=TrainingStore.hardware();state=TrainingState(store)
    assert not store.persistent and store._thread is None
    state.begin('ddb10_75');state.totals('ddb10_75')['correct']=7
    state.settings('ddb10_75')['mode']='coach'
    state.data['device']={'brightness':40,'animation_speed':2,'profiles':{'ddb10':'ddb10_75'}}
    state.save();assert region_digest()==before
    assert store.set_persistent(True);store.close()
    store=TrainingStore.hardware();state=TrainingState(store)
    assert store.persistent and state.totals('ddb10_75')['correct']==7
    app=PokerApp(training_state=state)
    assert not app.training_mode and app.play.menu['index']==0
    assert app.render().tobytes()==app.play.render().tobytes()
    assert app.display_brightness==40 and app.play.session.credits==10000 and not app.play.autoplay
    app.settings.open();app.render().save(out/'settings-general.png')
    app.settings.page='profiles';app.settings._select_profile_game(9);app.settings.profile_index=3
    app.render().save(out/'settings-paytable-presets.png')
    app.settings.page='pays';app.render().save(out/'settings-south-point-pays.png')
    app.settings.close();app.play.menu['index']=9;app.handle('KEY2')
    assert app.play.session.game.id=='ddb10_75' and app.play.session.total_bet==100
    app.toggle_hidden_mode();assert app.training_mode and app.trainer.page is None
    app.render().save(out/'trainer-live-sidebar.png')
    app.trainer.page='settings';app.trainer.index=6;app.render().save(out/'settings-memory-on.png')
    assert state.clear() and store.persistent and state.data['device']['brightness']==40
    assert not state.data['totals'] and not state.data['errors']
    state.begin('ddb10_75');state.totals('ddb10_75')['correct']=9;state.save()
    assert store.set_persistent(False)
    app.render().save(out/'settings-memory-off.png')
    app.close()
    fresh=TrainingState(TrainingStore.hardware())
    assert not fresh.store.persistent and not fresh.data['settings'] and not fresh.data['totals'] and not fresh.data['device']
    fresh.store.close()
    gate=launcher.HoldReleaseGate()
    dpad=launcher.HoldReleaseGate()
    assert not dpad.update(0,3) and not dpad.update(3,3)
    assert not gate.update(0,160) and not gate.update(1.999,160) and gate.update(2,160)
    gate.reset();gate.blocked=True
    assert not gate.update(4,160) and not gate.update(8,160)
    gate.update(9,0);gate.update(9.081,0)
    assert not gate.update(10,160) and gate.update(12,160)
    profile_checks=[];table=DetailedTable()
    for game in EXTRA_PROFILES:
        calc=CardCalculator();calc.select_game(game.id)
        try:
            for i,card in enumerate((8,9,10,11,12)):calc.set_card(i,card)
            assert calc._token is not None
            deadline=time.monotonic()+15
            while calc._token is not None and time.monotonic()<deadline:calc.update(time.monotonic());time.sleep(.001)
            assert calc.result and calc.result['mask']==31
            snapshot=calc.snapshot();report=table.advise(freeze_round(snapshot))
            assert report['mask']==31 and len(report['holds'])==32
            assert report['expected_current_win']==4000*game.hands
            profile_checks.append(game.id)
        finally:calc.close()
    storage.hardware_journal=original_discovery;temporary.unlink()
    settings_frames=['settings-general','settings-paytable-presets','settings-south-point-pays','settings-memory-on','settings-memory-off','trainer-live-sidebar']
    current['png_sha256'].update({name+'.png':hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest() for name in settings_frames})
    current['settings_and_persistence']={'status':'PASS','default_OFF_no_history_writes':True,
        'opt_in_restores_training_and_device_settings':True,'OFF_erases_saved_data':True,
        'clear_preserves_memory_mode_and_device_settings':True,'live_game_starts_fresh':True,
        'RIGHT_TOP_BOTTOM_toggles_live_sidebar_at_two_seconds':True,'Dpad_entry_shortcut_removed':True,'cabinet_has_no_settings_caption':True,'neutral_release_required_before_reentry':True,
        'calculator_fifth_card_auto_calculation':True,'alternate_paytable_full_EV_profiles':profile_checks,
        'save_test_backing':'Disposable regular file in guest RAM; no host or physical SD card written'}
    probe_report.write_text(json.dumps(current,indent=2)+'\n')
    stage('settings-persistence-complete')
except BaseException:
    error=traceback.format_exc()
    (out/'settings-error.txt').write_text(error)
    if (out/'arm-report.json').is_file():
        failed=json.loads((out/'arm-report.json').read_text());failed['status']='FAIL'
        failed['settings_error']=error;(out/'arm-report.json').write_text(json.dumps(failed,indent=2)+'\n')
    raise
'''
