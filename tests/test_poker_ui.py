import copy
import hashlib
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload/opt/dino'))
from poker_engine import Session, PAYOUTS, MULTIPLIERS, RandomNotReady
from poker_ui import PokerUI, Renderer, PAYS

FONT_DIR = ROOT.parent / 'seedconsole-dualboot/build/signer/source/src/seedsigner/resources/fonts'


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value


class PokerUITests(unittest.TestCase):
    def make_ui(self, credits=10000):
        ui = PokerUI(Session(credits=credits, rng=random.Random(250)), font_dir=FONT_DIR)
        ui.speed = 2
        return ui

    def focus_button(self, ui, index):
        ui.handle('KEY3')
        for _ in range(index): ui.handle('RIGHT')

    def test_deal_hold_draw_is_one_explicit_action_each(self):
        ui = self.make_ui()
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        ui.handle('RIGHT'); ui.handle('CENTER')
        self.assertEqual(ui.session.held, [False, True, False, False, False])
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(len(ui.session.hands), 10)
        self.assertTrue(all(hand[1] == ui.session.initial[1] for hand in ui.session.hands))
        self.assertEqual(ui.session.rounds, 1)

    def test_gold_controls_are_navigable_without_spending(self):
        ui = self.make_ui()
        self.focus_button(ui, 0)
        self.assertEqual(ui.button_focus, 0)
        ui.handle('CENTER')
        self.assertEqual(ui.menu['page'], 'paytable')
        ui.handle('RIGHT')
        self.assertEqual(ui.menu['bet'], 2)
        self.assertEqual(ui.session.bet_per_hand, 10)
        self.assertEqual(ui.session.credits, 10000)
        ui.handle('KEY2')
        self.assertIsNone(ui.menu)
        self.assertEqual(ui.button_focus, 0)
        ui.handle('KEY3')
        self.assertIsNone(ui.button_focus)

    def test_bet_control_cycles_actual_stakes_only_between_hands(self):
        ui = self.make_ui()
        self.focus_button(ui, 4)
        ui.handle('CENTER')
        self.assertEqual(ui.session.bet_per_hand, 1)
        self.assertEqual(ui.session.total_bet, 10)
        ui.handle('KEY3'); ui.handle('KEY2')
        self.focus_button(ui, 4)
        ui.handle('CENTER')
        self.assertEqual(ui.session.bet_per_hand, 1)
        self.assertEqual(ui.session.phase, 'hold')

    def test_bet_max_selects_ten_and_deals(self):
        ui = self.make_ui()
        ui.session.set_bet_per_hand(1)
        self.focus_button(ui, 5)
        ui.handle('CENTER')
        self.assertEqual(ui.session.bet_per_hand, 10)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        self.assertIsNone(ui.button_focus)

    def test_speed_control_cycles_nonblocking_speeds(self):
        ui = self.make_ui()
        self.focus_button(ui, 2)
        ui.handle('CENTER')
        self.assertEqual(ui.speed, 0)
        ui.handle('CENTER')
        self.assertEqual(ui.speed, 1)
        self.assertEqual(ui.session.phase, 'ready')

    def test_help_pages_and_return_do_not_change_game(self):
        ui = self.make_ui()
        self.focus_button(ui, 0); ui.handle('CENTER'); ui.handle('CENTER')
        self.assertEqual(ui.menu, {'page': 'controls', 'index': 0})
        ui.handle('KEY2')
        self.assertEqual(ui.menu['index'], 1)
        ui.handle('KEY3')
        self.assertIsNone(ui.menu)
        self.assertEqual(ui.session.credits, 10000)

    def test_add_credit_control_preserves_earned_multipliers(self):
        ui = self.make_ui()
        ui.session.multipliers = [2, 3, 4, 8, 10, 12, 1, 2, 3, 4]
        self.focus_button(ui, 1); ui.handle('CENTER')
        self.assertEqual(ui.menu['page'], 'more_games')
        ui.handle('KEY2')
        self.assertEqual(ui.session.credits, 20000)
        self.assertEqual(ui.session.multipliers, [2, 3, 4, 8, 10, 12, 1, 2, 3, 4])
        self.assertIsNone(ui.menu)

    def test_insufficient_credit_prompt_refills_without_auto_deal(self):
        ui = self.make_ui(20)
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'ready')
        self.assertTrue(ui.notice)
        self.assertEqual(ui.render().size, (320, 240))
        ui.handle('KEY2')
        self.assertEqual(ui.session.credits, 10020)
        self.assertEqual(ui.session.phase, 'ready')
        self.assertIsNone(ui.notice)

    def test_all_hands_and_card_focus_wrap_and_inspect(self):
        ui = self.make_ui()
        ui.handle('LEFT'); ui.handle('UP')
        self.assertEqual((ui.selected_card, ui.selected_hand), (4, 9))
        ui.handle('KEY2'); ui.handle('KEY2'); ui.handle('UP'); ui.handle('CENTER')
        self.assertEqual(ui.menu, {'page': 'inspect', 'index': 9})
        ui.handle('DOWN')
        self.assertEqual(ui.menu['index'], 0)
        ui.handle('KEY3')
        self.assertIsNone(ui.menu)

    def test_nonblocking_animation_updates_without_debiting_again(self):
        clock = Clock()
        ui = PokerUI(Session(rng=random.Random(250)), font_dir=FONT_DIR, clock=clock)
        ui.speed = 0
        ui.handle('KEY2')
        self.assertIsNotNone(ui._animation)
        self.assertEqual(ui.session.credits, 9900)
        self.assertFalse(ui.update(clock.value))
        clock.value += 0.2
        self.assertTrue(ui.update(clock.value))
        self.assertEqual(ui.render().size, (320, 240))
        self.assertEqual(ui.session.credits, 9900)
        clock.value += 2
        self.assertTrue(ui.update(clock.value))
        self.assertIsNone(ui._animation)
        self.assertEqual(ui.session.phase, 'hold')

    def test_middle_skips_animation_without_drawing_or_dealing_twice(self):
        clock = Clock()
        ui = PokerUI(Session(rng=random.Random(250)), font_dir=FONT_DIR, clock=clock)
        ui.handle('KEY2'); ui.handle('KEY2')
        self.assertIsNone(ui._animation)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'result')
        self.assertIsNotNone(ui._animation)
        credits = ui.session.credits
        ui.handle('KEY2')
        self.assertEqual(ui.session.credits, credits)
        self.assertEqual(ui.session.rounds, 1)
        self.assertIsNone(ui._animation)

    def test_renderer_does_not_mutate_state(self):
        ui = self.make_ui()
        ui.handle('KEY2'); ui.handle('KEY2')
        state = ui.session.snapshot()
        original = copy.deepcopy(state)
        for selected in range(10):
            image = ui.renderer.render(state, selected_hand=selected)
            self.assertEqual((image.mode, image.size), ('RGB', (320, 240)))
        self.assertEqual(state, original)

    def test_all_views_are_native_rgb_frames(self):
        ui = self.make_ui()
        states = [ui.session.snapshot()]
        ui.handle('KEY2'); states.append(ui.session.snapshot())
        ui.handle('KEY2'); states.append(ui.session.snapshot())
        for state in states:
            for menu in (None, {'page': 'paytable', 'bet': 1}, {'page': 'paytable', 'bet': 5},
                         {'page': 'controls', 'index': 0}, {'page': 'controls', 'index': 1},
                         {'page': 'more_games'}, {'page': 'hands'}, {'page': 'reset_confirm'},
                         {'page': 'inspect', 'index': 0}):
                image = ui.renderer.render(state, menu=menu)
                self.assertEqual((image.mode, image.size), ('RGB', (320, 240)))
                self.assertGreater(len(image.getcolors(maxcolors=100000)), 10)

    def test_displayed_paytable_uses_engine_constants(self):
        self.assertEqual({key: pay for key, pay, _ in PAYS}, PAYOUTS)
        self.assertEqual({key: multiplier for key, _, multiplier in PAYS}, MULTIPLIERS)

    def test_paytable_draws_reduced_coin_royal_and_bonus_schedule(self):
        ui = self.make_ui()
        text = []
        original = ui.renderer.text
        def capture(draw, xy, value, *args, **kwargs):
            text.append(str(value))
            return original(draw, xy, value, *args, **kwargs)
        ui.renderer.text = capture
        ui.renderer.render(ui.session.snapshot(), menu={'page': 'paytable', 'bet': 1})
        for value in ('250', '500', '750', '1000', '4000', '12X', '10X', '8X'):
            self.assertIn(value, text)

    def test_select_hands_cycles_only_at_one_credit(self):
        ui = self.make_ui()
        self.focus_button(ui, 3)
        ui.handle('CENTER')
        self.assertEqual(ui.session.num_hands, 10)
        ui.session.set_bet_per_hand(1)
        ui.handle('CENTER')
        self.assertEqual(ui.session.num_hands, 1)
        ui.handle('CENTER')
        self.assertEqual(ui.session.num_hands, 2)
        self.assertEqual(ui.session.total_bet, 2)
        self.assertEqual(ui.session.credits, 10000)
        ui.handle('KEY3'); ui.handle('UP')
        self.assertEqual(ui.selected_hand, 1)

    def test_bet_per_hand_resets_to_ten_one_credit_hands_after_round(self):
        ui = self.make_ui()
        ui.handle('KEY2'); ui.handle('KEY2')
        self.focus_button(ui, 4); ui.handle('CENTER')
        self.assertEqual(ui.session.phase, 'ready')
        self.assertEqual(ui.session.num_hands, 10)
        self.assertEqual(ui.session.bet_per_hand, 1)
        self.assertEqual(ui.session.hands, [])

    def test_insufficient_bet_max_selects_affordable_bet_without_deal(self):
        ui = self.make_ui(35)
        ui.session.set_bet_per_hand(1)
        self.focus_button(ui, 5); ui.handle('CENTER')
        self.assertEqual(ui.session.phase, 'ready')
        self.assertEqual(ui.session.bet_per_hand, 3)
        self.assertEqual(ui.session.num_hands, 10)
        self.assertEqual(ui.session.credits, 35)
        self.assertIsNone(ui._animation)

    def test_inactive_pending_multipliers_dim_without_extra_banner(self):
        ui = self.make_ui()
        ui.session.set_bet_per_hand(1)
        ui.session.set_num_hands(1)
        ui.session.multipliers = [1, 12, 1, 1, 1, 1, 1, 1, 1, 1]
        words = []
        original = ui.renderer.text
        def capture(draw, xy, value, *args, **kwargs):
            words.append(str(value))
            return original(draw, xy, value, *args, **kwargs)
        ui.renderer.text = capture
        ui.render()
        self.assertNotIn('INACTIVE X LOST ON DEAL', words)
        # The pending badge stays visible, using the website's dim presentation.
        matching = [key for key in ui.renderer.scaled if key[0] == 'opacity' and key[1] == 'multipliers/12x_2.png' and key[-1] == .6]
        self.assertEqual(len(matching), 1)
        ui.session.set_num_hands(10)
        words.clear(); ui.render()
        self.assertNotIn('INACTIVE X LOST ON DEAL', words)

    def test_control_menu_key_skips_animation_without_deal(self):
        ui = PokerUI(Session(rng=random.Random(250)), font_dir=FONT_DIR)
        ui.handle('KEY2')
        self.assertIsNotNone(ui._animation)
        ui.handle('KEY3')
        self.assertIsNone(ui._animation)
        self.assertEqual(ui.button_focus, 0)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)

    def test_dealt_royal_reveals_then_rolls_up_without_hold_phase(self):
        class RoyalSampler:
            def sample(self, population, count):
                return [8, 9, 10, 11, 12][:count]
        clock = Clock()
        ui = PokerUI(Session(rng=RoyalSampler()), font_dir=FONT_DIR, clock=clock)
        ui.speed = 0
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(ui.session.total_win, 40000)
        self.assertIsNotNone(ui._animation)
        self.assertEqual(ui._visual['_reveal'], 1)
        self.assertEqual(ui._visual['held'], [False]*5)
        self.assertEqual(ui._visual['total_win'], 0)
        self.assertEqual(ui._visual['credits'], 9900)
        clock.value += 0.8
        ui.update(clock.value)
        self.assertEqual(ui._visual['_reveal'], 5)
        self.assertTrue(all(ui._visual['held']))
        self.assertGreater(ui._visual['total_win'], 0)
        self.assertLess(ui._visual['total_win'], 40000)
        clock.value += 1
        ui.update(clock.value)
        self.assertIsNone(ui._animation)
        self.assertEqual(ui.session.credits, 49900)

    def test_paytable_preview_is_bounded_and_persists_without_changing_wager(self):
        ui = self.make_ui()
        self.focus_button(ui, 0); ui.handle('CENTER')
        self.assertEqual(ui.menu['bet'], 1)
        ui.handle('LEFT')
        self.assertEqual(ui.menu['bet'], 1)
        observed = []
        for _ in range(5):
            ui.handle('RIGHT'); observed.append(ui.menu['bet'])
        self.assertEqual(observed, [2, 3, 4, 5, 10])
        ui.handle('RIGHT')
        self.assertEqual(ui.menu['bet'], 10)
        ui.handle('LEFT'); ui.handle('LEFT')
        self.assertEqual(ui.menu['bet'], 4)
        ui.handle('KEY2'); ui.handle('CENTER')
        self.assertEqual(ui.menu['bet'], 4)
        self.assertEqual(ui.session.bet_per_hand, 10)
        self.assertEqual(ui.session.credits, 10000)
        image = ui.renderer.render(ui.session.snapshot(), menu={'page': 'paytable', 'bet': 10})
        source = ui.renderer.render_paytable_source(ui.session.snapshot(), {'bet': 10})
        self.assertEqual(source.getpixel((460, 210)), (176, 0, 0))
        pasted = []
        original_paste = ui.renderer.paste
        def capture(image, name, *args, **kwargs):
            pasted.append(name)
            return original_paste(image, name, *args, **kwargs)
        ui.renderer.paste = capture
        ui.renderer.render(ui.session.snapshot(), menu={'page': 'paytable', 'bet': 10})
        self.assertNotIn('help/buttons/betup.png', pasted)
        self.assertIn('help/buttons/betdown.png', pasted)
        pasted.clear()
        ui.renderer.render(ui.session.snapshot(), menu={'page': 'paytable', 'bet': 1})
        self.assertIn('help/buttons/betup.png', pasted)
        self.assertNotIn('help/buttons/betdown.png', pasted)

    def test_condensed_control_labels_and_footer_ink_stay_in_bounds(self):
        from PIL import Image
        ui = self.make_ui()
        for label in ('SEE PAYS/HELP', 'SELECT HANDS', 'BET PER HAND', 'SPEED >>>'):
            image = Image.new('RGB', (320, 240))
            left, top, right, bottom = ui.renderer.pill(image, (0, 221, 43, 234), label, size=7)
            self.assertGreaterEqual(left, 4)
            self.assertGreaterEqual(top, 224)
            self.assertLessEqual(right, 39)
            self.assertLessEqual(bottom, 231)
        bounds = ui.renderer.fitted_label(image, (70, 235, 250, 239), 'Double Dbl Bonus', 6)
        self.assertGreaterEqual(bounds[1], 235)
        self.assertLessEqual(bounds[3], 239)

    def test_rendered_help_and_menus_do_not_disclose_hidden_wallet_entry(self):
        import re
        ui = self.make_ui()
        strings = []
        original_text = ui.renderer.text
        original_fitted = ui.renderer.fitted_label
        def text(draw, xy, value, *args, **kwargs):
            strings.append(str(value))
            return original_text(draw, xy, value, *args, **kwargs)
        def fitted(image, box, value, *args, **kwargs):
            strings.append(str(value))
            return original_fitted(image, box, value, *args, **kwargs)
        ui.renderer.text = text
        ui.renderer.fitted_label = fitted
        states = [ui.session.snapshot()]
        ui.handle('KEY2'); states.append(ui.session.snapshot())
        ui.handle('KEY2'); states.append(ui.session.snapshot())
        menus = (None, *({'page': 'controls', 'index': n} for n in range(4)),
                 {'page': 'paytable', 'bet': 1}, {'page': 'paytable', 'bet': 10},
                 {'page': 'options', 'index': 0}, {'page': 'more_games'},
                 {'page': 'hands'}, {'page': 'reset_confirm'}, {'page': 'inspect', 'index': 0})
        for state in states:
            for menu in menus:
                ui.renderer.render(state, menu=menu)
        rendered = '\n'.join(strings)
        self.assertIsNone(re.search(r'seedsigner|\bseed\b|wallet|outer|k1\s*\+\s*k3|release all|entry chord', rendered, re.I))
        # Official help is now bitmap artwork; its audited pixels are separately
        # pinned below. Capture all locally drawn text without inventing OCR.

    def test_entropy_blocked_deal_retries_once_without_spending_or_refilling(self):
        class OnceBlockedSampler:
            def __init__(self):
                self.rng = random.Random(250)
                self.calls = 0
            def sample(self, population, count):
                self.calls += 1
                if self.calls == 1: raise RandomNotReady('not ready')
                return self.rng.sample(population, count)
        sampler = OnceBlockedSampler()
        ui = PokerUI(Session(rng=sampler), font_dir=FONT_DIR)
        ui.speed = 2
        before = ui.session.snapshot()
        ui.handle('KEY2')
        self.assertEqual(ui.session.snapshot(), before)
        self.assertEqual(ui.notice, 'Shuffling is getting ready')
        self.assertTrue(ui._entropy_notice)
        self.assertFalse(ui._credit_notice)
        self.assertEqual(ui.render().size, (320, 240))
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)
        self.assertEqual(sampler.calls, 2)
        self.assertIsNone(ui.notice)
        self.assertFalse(ui._entropy_notice)

    def test_entropy_blocked_draw_preserves_hold_and_retries_settlement_once(self):
        class DrawBlockedSampler:
            def __init__(self):
                self.rng = random.Random(250)
                self.calls = 0
            def sample(self, population, count):
                self.calls += 1
                if self.calls == 2: raise RandomNotReady('not ready')
                return self.rng.sample(population, count)
        sampler = DrawBlockedSampler()
        ui = PokerUI(Session(rng=sampler), font_dir=FONT_DIR)
        ui.speed = 2
        ui.session.multipliers = [12, 3, 4, 8, 10, 2, 1, 1, 1, 1]
        ui.handle('KEY2'); ui.handle('CENTER'); ui.handle('RIGHT'); ui.handle('CENTER')
        before = ui.session.snapshot()
        ui.handle('KEY2')
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui._entropy_notice)
        self.assertFalse(ui._credit_notice)
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'result')
        self.assertEqual(ui.session.rounds, 1)
        self.assertEqual(ui.session.credits, 9900+ui.session.total_win)
        self.assertEqual(ui.session.held, before['held'])
        self.assertEqual(ui.session.active_multipliers, before['active_multipliers'])
        self.assertEqual(sampler.calls, 12)

    def test_entropy_blocked_bet_max_retry_preserves_max_bet_intent(self):
        class OnceBlockedSampler:
            def __init__(self):
                self.rng = random.Random(250)
                self.calls = 0
            def sample(self, population, count):
                self.calls += 1
                if self.calls == 1: raise RandomNotReady('not ready')
                return self.rng.sample(population, count)
        ui = PokerUI(Session(rng=OnceBlockedSampler()), font_dir=FONT_DIR)
        ui.speed = 2
        ui.session.set_bet_per_hand(1); ui.session.set_num_hands(3)
        before = ui.session.snapshot()
        self.focus_button(ui, 5); ui.handle('CENTER')
        self.assertEqual(ui.session.snapshot(), before)
        self.assertTrue(ui._retry_max_bet)
        ui.handle('KEY2')
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.num_hands, 10)
        self.assertEqual(ui.session.bet_per_hand, 10)
        self.assertEqual(ui.session.credits, 9900)

    def test_entropy_notice_keeps_game_controls_responsive_and_neutral(self):
        class BlockedSampler:
            def sample(self, population, count): raise RandomNotReady('not ready')
        ui = PokerUI(Session(rng=BlockedSampler()), font_dir=FONT_DIR)
        before = ui.session.snapshot()
        ui.handle('KEY2')
        words = []
        original = ui.renderer.text
        def capture(draw, xy, value, *args, **kwargs):
            words.append(str(value))
            return original(draw, xy, value, *args, **kwargs)
        ui.renderer.text = capture
        ui.render()
        self.assertIn('Shuffling is getting ready', words)
        self.assertIn('D-PAD CENTER: RETRY', words)
        self.assertNotIn('D-PAD CENTER: ADD 10,000', words)
        self.assertNotIn('seed', '\n'.join(words).lower())
        self.assertNotIn('wallet', '\n'.join(words).lower())
        ui.handle('KEY3')
        self.assertEqual(ui.button_focus, 0)
        self.assertIsNone(ui.notice)
        self.assertEqual(ui.session.snapshot(), before)


    def test_actual_card_mapping_and_face_pixels_are_unchanged_by_focus(self):
        ui = self.make_ui()
        renderer = ui.renderer
        for card, source in ((0, 13), (12, 25), (13, 39), (25, 51),
                             (26, 26), (38, 38), (39, 0), (51, 12)):
            self.assertEqual(renderer.source_card(card), source)
            expected = renderer.sprite('cards/'+str(source)+'.png', (83, 119))
            self.assertEqual(renderer.card(card, 83, 119, selected=True).tobytes(), expected.tobytes())
        ui.handle('KEY2')
        state = ui.session.snapshot()
        first = renderer.render_source(state, selected_card=0)
        other = renderer.render_source(state, selected_card=4)
        # Logical art is independent of the native navigation overlay.
        self.assertEqual(first.crop((103, 268, 536, 375)).tobytes(),
                         other.crop((103, 268, 536, 375)).tobytes())
        self.assertEqual(first.tobytes(), other.tobytes())
        self.assertNotEqual(renderer.render(state, selected_card=0).tobytes(),
                            renderer.render(state, selected_card=4).tobytes())
        self.assertEqual(first.getpixel((10, 100)), renderer.background.getpixel((10, 100)))

    def test_badge_animation_uses_declared_cadence_without_game_actions(self):
        clock = Clock()
        ui = PokerUI(Session(rng=random.Random(250)), clock=clock)
        before = ui.session.snapshot()
        initial = ui.render()
        self.assertFalse(ui.update(100.199))
        self.assertTrue(ui.update(100.2))
        self.assertEqual(ui._badge_frame, 1)
        self.assertFalse(ui.update(100.399))
        changed = ui.render()
        from PIL import ImageChops
        bbox = ImageChops.difference(initial, changed).getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[0], 270)
        self.assertLessEqual(bbox[2], 318)
        self.assertGreaterEqual(bbox[1], 128)
        self.assertLessEqual(bbox[3], 192)
        self.assertEqual(ui.session.snapshot(), before)
        ui.session.set_feature(False)
        ui.update(101.0)
        self.assertEqual(ui._badge_frame, 0)
        self.assertFalse(ui.update(101.299))
        self.assertTrue(ui.update(101.3))
        self.assertEqual(ui._badge_frame, 1)

    def test_help_navigation_has_four_normal_and_two_in_hand_bounded_pages(self):
        ui = self.make_ui()
        self.focus_button(ui, 0); ui.handle('CENTER'); ui.handle('CENTER')
        for _ in range(9): ui.handle('RIGHT')
        self.assertEqual(ui.menu['index'], 3)
        for _ in range(9): ui.handle('LEFT')
        self.assertEqual(ui.menu['index'], 0)
        ui.handle('KEY3'); ui.handle('KEY3'); ui.handle('KEY2')
        self.focus_button(ui, 0); ui.handle('CENTER'); ui.handle('CENTER')
        for _ in range(9): ui.handle('KEY2')
        self.assertEqual(ui.menu['index'], 1)
        self.assertEqual(ui.session.phase, 'hold')
        self.assertEqual(ui.session.credits, 9900)

    def test_visible_help_bitmaps_match_all_six_audited_reference_assets(self):
        # Human-inspected actual public help contains poker rules/control labels
        # only. Pin its pixels, instead of pretending a string capture reads PNGs.
        expected = {'help/helpdraw1.png': 'b92cb46e490d12a13e66baef57eeed5abf434b4c066b1762fc6a7f94d3a012b3', 'help/helpdraw2.png': '1dea62563b48aea0f8b4a896a3515532f4c41e22df5f2f9e27e82c96146351b9', 'help/helpscreen1.png': '842dee63b728cabca0f3dfca86ea736bb68d4e99e290c579d7e983149fe892f5', 'help/helpscreen2.png': '822555ed57993d606b64ced6fd2f1da9798ab32bca6b76df9aea03c0ecc36109', 'help/helpscreen3.png': 'd6bd8ef58804c4a4cb994fcbe162dbecf5c8727a80efd31eadd93a7ad963bc1b', 'help/helpscreen4.png': '36b2fd99628622b7a93c6ac972f4e8517eb466ffc0b3eaafe92211da608f609f'}
        ui = self.make_ui()
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ui.renderer.asset_dir/name).read_bytes()).hexdigest(), digest)
        for phase, prefix, count in (('ready', 'helpscreen', 4), ('hold', 'helpdraw', 2)):
            state = ui.session.snapshot(); state['phase'] = phase
            for index in range(count):
                source = ui.renderer.render_help_source(state, {'index': index})
                asset = ui.renderer.assets['help/'+prefix+str(index+1)+'.png']
                self.assertEqual(source.crop((20, 24, 620, 380)).tobytes(),
                                 asset.convert('RGB').crop((0, 0, 600, 356)).tobytes())

    def test_primary_render_uses_cached_art_and_glyphs_without_file_reads(self):
        from unittest.mock import patch
        ui = self.make_ui()
        ui.handle('KEY2'); ui.handle('KEY2')
        state = ui.session.snapshot()
        state['active_multipliers'] = [2, 3, 4, 8, 10, 12, 1, 2, 3, 4]
        with patch('PIL.Image.open', side_effect=AssertionError('Runtime image decode after constructor')):
            for menu in (None, {'page': 'paytable', 'bet': 10}, {'page': 'controls', 'index': 3}):
                self.assertEqual(ui.renderer.render(state, menu=menu).size, (320, 240))
        self.assertLessEqual(len(ui.renderer.text_cache), 512)

    def test_atlas_glyph_cache_preserves_exact_antialiased_alpha(self):
        from PIL import Image
        renderer = self.make_ui().renderer
        renderer._text_run('A', 15, True)
        glyph = renderer.fonts['bold']['sizes']['15']['glyphs']['A']
        x, y, w, h = (glyph[key] for key in ('x', 'y', 'width', 'height'))
        with Image.open(renderer.asset_dir/'fonts/arial-bold.png') as atlas:
            alpha = atlas.convert('RGBA').getchannel('A').crop((x, y, x+w, y+h))
        cached = renderer.glyph_cache[('bold', '15', 'A')]
        self.assertEqual(cached.mode, 'L')
        self.assertEqual(cached.tobytes(), alpha.tobytes())
        self.assertTrue(any(0 < value < 255 for value in cached.getdata()))
        run = renderer._text_run('A', 15, True)[0]
        self.assertEqual(run.crop((0, 0, w, h)).tobytes(), alpha.tobytes())

    def test_win_text_ink_fits_the_actual_black_banner(self):
        from PIL import Image
        renderer = self.make_ui().renderer
        seen = []
        original = renderer.text
        def capture(draw, xy, text, size=11, fill=(255, 255, 255), bold=False):
            mask = renderer._text_run(text, size, bold)[0]
            bbox = mask.getbbox()
            if bbox:
                seen.append((xy[0]+bbox[0], xy[1]+bbox[1], xy[0]+bbox[2], xy[1]+bbox[3]))
            return original(draw, xy, text, size, fill, bold)
        renderer.text = capture
        for category, pay, _ in PAYS[:-1]:
            seen.clear()
            renderer.win_indicator(Image.new('RGB', (640, 480)), 1,
                {'category': category, 'payout': pay*5*12, 'base_payout': pay*5, 'multiplier': 12})
            x, y, width, height = renderer.HANDS[1]
            cx, cy = x+width/2, y+.65*height
            self.assertEqual(len(seen), 2)
            for left, top, right, bottom in seen:
                self.assertGreaterEqual(left, cx-62)
                self.assertLessEqual(right, cx+62)
                self.assertGreaterEqual(top, cy-10)
                self.assertLessEqual(bottom, cy+17)

    def test_whole_text_runs_match_independent_source_font_rasterization(self):
        from PIL import Image, ImageFont, ImageDraw
        base = Path('/System/Library/Fonts/Supplemental')
        if not (base/'Arial.ttf').is_file():
            self.skipTest('Host Arial source fonts unavailable; runtime needs only PNG atlases')
        renderer = self.make_ui().renderer
        cases = (('10000', 15, True), ('10000', 16, True),
                 ('Double Dbl Bonus', 11, False), ('Jacks or Better', 11, False),
                 ('ROYAL FLUSH', 13.076923, True), ('JACKS OR BETTER', 13.076923, True))
        for text, size, bold in cases:
            font = ImageFont.truetype(str(base/('Arial Bold.ttf' if bold else 'Arial.ttf')), size)
            actual, _, bx, by = renderer._text_run(text, size, bold)
            expected = Image.new('L', actual.size, 0)
            ImageDraw.Draw(expected).text((-bx, -by), text, font=font, anchor='ls', fill=255)
            self.assertEqual(actual.tobytes(), expected.tobytes(), (text, size, bold))

    def test_reference_caption_and_paytable_bet_use_pure_white(self):
        ui = self.make_ui()
        calls = []
        original = ui.renderer.text
        def capture(draw, xy, text, size=11, fill=(255, 255, 255), bold=False):
            calls.append((str(text), fill))
            return original(draw, xy, text, size, fill, bold)
        ui.renderer.text = capture
        ui.renderer.render_source(ui.session.snapshot())
        ui.renderer.render_paytable_source(ui.session.snapshot(), {'bet': 1})
        for label in ('Double Dbl Bonus', 'BET'):
            self.assertIn((label, (255, 255, 255)), calls)
        self.assertNotIn((255, 255, 250), [fill for _, fill in calls])

    def test_badge_cache_matches_full_lanczos_composition_for_every_frame(self):
        ui = self.make_ui()
        states = [ui.session.snapshot()]
        ui.handle('KEY2'); ui.handle('CENTER'); states.append(ui.session.snapshot())
        ui.handle('KEY2'); states.append(ui.session.snapshot())
        ui.session.set_bet_per_hand(1); ui.session.set_num_hands(1)
        ui.session.multipliers = [2, 3, 4, 8, 10, 12, 1, 2, 3, 4]
        states.append(ui.session.snapshot())
        for state in states:
            count = 13 if state['feature'] else 7
            for frame in range(count):
                state['_badge_frame'] = frame
                for focus in (None, 3):
                    state['_button_focus'] = focus
                    actual = ui.renderer.render(state, selected_card=2)
                    expected = ui.renderer.render_uncached(state, selected_card=2)
                    self.assertEqual(actual.tobytes(), expected.tobytes(),
                                     (state['phase'], state['feature'], frame, focus))

    def test_badge_and_focus_updates_skip_card_composition_and_full_resize(self):
        from unittest.mock import patch
        from PIL import Image
        ui = self.make_ui(); ui.handle('KEY2')
        state = ui.session.snapshot()
        renderer = ui.renderer
        renderer.render(state)
        logical_board = renderer._normal_board
        sizes = []
        original_resize = Image.Image.resize
        def resize(image, size, *args, **kwargs):
            sizes.append((image.size, tuple(size)))
            return original_resize(image, size, *args, **kwargs)
        with patch.object(renderer, '_render_board', side_effect=AssertionError('Recomposed static board')):
            with patch.object(Image.Image, 'resize', new=resize):
                for frame in range(1, 13):
                    state['_badge_frame'] = frame
                    renderer.render(state)
                self.assertEqual(len(sizes), 12)
                self.assertEqual(set(sizes), {((112, 152), (56, 76))})
                sizes.clear()
                for card in range(5): renderer.render(state, selected_card=card)
                for button in range(7):
                    state['_button_focus'] = button
                    renderer.render(state)
                self.assertEqual(sizes, [])
        self.assertIs(renderer._normal_board, logical_board)

    def test_nested_snapshot_changes_replace_the_single_board_cache(self):
        ui = self.make_ui(); ui.handle('KEY2'); ui.handle('KEY2')
        state = ui.session.snapshot()
        state['results'][0] = {'category': 'high_pair', 'base_payout': 5,
                               'payout': 5, 'multiplier': 1, 'next_multiplier': 2}
        renderer = ui.renderer
        renderer.render(state)
        def check_mutation(change):
            previous = renderer._normal_board
            change()
            actual = renderer.render(state)
            self.assertIsNot(renderer._normal_board, previous)
            self.assertEqual(actual.tobytes(), renderer.render_uncached(state).tobytes())
        check_mutation(lambda: state['held'].__setitem__(0, not state['held'][0]))
        check_mutation(lambda: state['hands'][0].__setitem__(0, (state['hands'][0][0]+1) % 52))
        check_mutation(lambda: state['results'][0].__setitem__('payout', 10))
        check_mutation(lambda: state['multipliers'].__setitem__(5, 12))
        # A snapshot mutation cannot alter the previously detached immutable key.
        old_key = renderer._normal_key
        state['hands'][1][1] = (state['hands'][1][1]+1) % 52
        self.assertEqual(renderer._normal_key, old_key)
        renderer.render(state)
        self.assertNotEqual(renderer._normal_key, old_key)

    def test_mutating_returned_frames_does_not_poison_render_cache(self):
        ui = self.make_ui(); ui.handle('KEY2')
        state = ui.session.snapshot()
        expected = ui.renderer.render(state).tobytes()
        returned = ui.renderer.render(state)
        returned.paste((0, 0, 0), (0, 0, 320, 240))
        self.assertEqual(ui.renderer.render(state).tobytes(), expected)
        logical = ui.renderer.render_source(state)
        logical.paste((255, 0, 0), (0, 0, 640, 480))
        self.assertEqual(ui.renderer.render(state).tobytes(), expected)

    def test_native_focus_is_visible_without_obscuring_held_tags_or_footer(self):
        from PIL import Image
        ui = self.make_ui(); ui.handle('KEY2')
        ui.session.toggle_hold(2)
        state = ui.session.snapshot()
        renderer = ui.renderer
        plain = renderer.render_source_uncached(state).resize((320, 240), Image.Resampling.LANCZOS)
        focus = renderer.render(state, selected_card=2)
        # Full native-value yellow ring and a large solid pointer are crisp.
        self.assertEqual(focus.getpixel((138, 150)), (255, 255, 0))
        self.assertEqual(focus.getpixel((159, 127)), (255, 255, 0))
        center = int(round((103+87*2+41)/2.0))
        held_box = (center-15, 184, center+15, 202)
        self.assertEqual(focus.crop(held_box).tobytes(), plain.crop(held_box).tobytes())
        for index, source_left in enumerate(renderer.BUTTON_X):
            state['_button_focus'] = index
            focus = renderer.render(state)
            left = int(source_left//2)
            self.assertEqual(focus.getpixel((left+12, 218)), (255, 255, 255))
            self.assertEqual(focus.getpixel((left+12, 219)), (255, 255, 255))
            self.assertEqual(focus.crop((0, 233, 320, 240)).tobytes(),
                             plain.crop((0, 233, 320, 240)).tobytes())

    def test_unknown_actions_and_wrong_screen_are_safe(self):
        ui = self.make_ui()
        self.assertFalse(ui.handle('ANYTHING'))
        self.assertFalse(ui.update(100.0))
        self.assertEqual(ui.session.phase, 'ready')
        with self.assertRaises(ValueError): PokerUI(width=240, height=240)


if __name__ == '__main__': unittest.main()
