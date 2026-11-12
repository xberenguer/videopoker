"""Offline 320x240 poker interface with private local reference artwork.

Only declared bitmap graphics and rasterized glyphs are loaded. No vendor game
code, network requests, account access or persistent financial state is used.
"""
import json
import math
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from poker_engine import CATEGORIES, PAYOUTS, MULTIPLIERS, RandomNotReady

WIDTH, HEIGHT = 320, 240
BG = (11, 0, 107)
GOLD = (255, 255, 0)
WHITE = (255, 255, 255)
RED = (185, 8, 12)
INK = (9, 10, 18)
MUTED = (194, 194, 214)
GREEN = (73, 252, 79)
BLUE = (18, 70, 155)
LABELS = {
    'royal_flush': 'ROYAL FLUSH', 'straight_flush': 'STRAIGHT FLUSH',
    'four_aces_kicker': '4 ACES W/ 2,3,4', 'four_234_kicker': '4 2s,3s,4s W/ A,2,3,4',
    'four_aces': '4 ACES', 'four_234': '4 2s,3s,4s', 'four_5k': '4 5s THRU Ks',
    'full_house': 'FULL HOUSE', 'flush': 'FLUSH', 'straight': 'STRAIGHT',
    'three_kind': '3 OF A KIND', 'two_pair': '2 PAIR',
    'high_pair': 'JACKS OR BETTER', 'nothing': 'NO WIN',
}
# The displayed schedule is the engine's own schedule, not a second math table.
PAYS = tuple((key, PAYOUTS[key], MULTIPLIERS[key]) for key in CATEGORIES)
BUTTONS = ('SEE PAYS/HELP', 'MORE GAMES', 'SPEED', 'SELECT HANDS',
           'BET PER HAND', 'BET MAX', 'DEAL')
OPTIONS = ('PAYTABLE', 'BONUS BET', 'NEW SESSION', 'CONTROLS', 'RETURN')


def _short_number(value):
    value = int(value)
    if abs(value) < 1_000_000:
        return str(value)
    return ('%.1fM' % (value / 1_000_000)).replace('.0M', 'M')


def _font_directory():
    return Path('/opt/src/seedsigner/resources/fonts')


class Renderer:
    """Private local bitmap renderer, composed at the reference's 640x480 size.

    Runtime artwork and Arial glyph pixels are declared in the checked manifest.
    All caches belong to this instance so the launcher can release them on exit.
    There is no runtime HTTP, vendor game code, font binary or account access.
    """
    SOURCE_SIZE = (640, 480)
    HANDS = ((103, 268, 433, 120), (74, 174, 137, 80), (284, 174, 137, 80),
             (496, 174, 137, 80), (74, 86, 137, 80), (284, 86, 137, 80),
             (496, 86, 137, 80), (74, 0, 137, 80), (284, 0, 137, 80), (496, 0, 137, 80))
    BUTTON_X = (0, 92, 184, 275, 367, 459, 551)
    WIN_ART = dict(zip(CATEGORIES[:-1], (3, 9, 4, 2, 2, 5, 10, 11, 12, 13, 14, 15, 16)))
    RESULT_LABELS = {
        'royal_flush': 'Royal Flush', 'straight_flush': 'Straight Flush',
        'four_aces_kicker': '4 Aces w/2,3,4', 'four_234_kicker': '4 2s,3s,4s w/Ace,2,3,4',
        'four_aces': '4 Aces', 'four_234': '4 2s,3s,4s', 'four_5k': '4 5s thru Ks',
        'full_house': 'Full House', 'flush': 'Flush', 'straight': 'Straight',
        'three_kind': '3 of a Kind', 'two_pair': '2 Pair', 'high_pair': 'Jacks or Better', 'nothing': '',
    }

    PAY_LABELS = {'four_aces_kicker': '4 ACES W/ 2,3,4',
                  'four_234_kicker': '4 2S,3S,4S W/ ACE 2,3,4'}

    def __init__(self, font_dir=None, asset_dir=None):
        # font_dir remains accepted for compatibility; runtime uses no TTF files.
        self.asset_dir = Path(asset_dir) if asset_dir else Path(__file__).resolve().parent/'assets/videopoker'
        self.manifest = json.loads((self.asset_dir/'manifest.json').read_text())
        if self.manifest.get('schema') != 1:
            raise ValueError('Unsupported artwork manifest')
        self.assets, self.scaled, self.text_cache, self.glyph_cache = {}, {}, OrderedDict(), {}
        self.fonts = self.manifest['glyph_atlases']
        for item in self.manifest['assets']:
            name = item['path']
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.png':
                raise ValueError('Invalid artwork path')
            with Image.open(self.asset_dir/relative) as opened:
                if opened.format != 'PNG' or opened.size != (item['width'], item['height']):
                    raise ValueError('Invalid artwork dimensions')
                # Glyphs only need a single alpha channel rather than four copies.
                self.assets[name] = opened.convert('RGBA').getchannel('A') if item['role'].startswith('glyph-atlas') else opened.convert('RGBA')
        self.card_cache = {}
        self.background = self.assets['backgrounds/uxgamebg.png'].convert('RGB')
        # One normal board and one native frame, replaced on any board change.
        # Badge ticks must not compose all fifty cards again on the Pi Zero.
        self._normal_key = None
        self._normal_board = None
        self._normal_native = None
        self._normal_badge = None
        # Build the complete finite set of card and control resizes once, not per frame.
        for name in ['cards/'+str(i)+'.png' for i in range(52)]+['cards/Back.png', 'cards/Back_Disabled.png']:
            for size in ((83, 119), (56, 80)):
                self.sprite(name, size)
        for name in self.assets:
            if name.startswith('gui/') and name not in ('gui/hold.png',) and not name.startswith('gui/speaker_'):
                self.sprite(name, (86, 30))
        for number in (2, 3, 4, 8, 10, 12):
            name = 'multipliers/'+str(number)+'x_2.png'
            asset = self.assets[name]
            for height in (16, 24):
                self.sprite(name, (int(round(asset.width*height/asset.height)), height))
        self.sprite('multipliers/nexthand.png', (25, 16))
        for number in self.WIN_ART.values():
            self.sprite('wins/payline'+str(number)+'.png', (130, 35))

    def sprite(self, name, size=None):
        image = self.assets[name]
        if size is None or image.size == size:
            return image
        key = (name, tuple(size))
        if key not in self.scaled:
            self.scaled[key] = image.resize(size, getattr(Image, 'Resampling', Image).BILINEAR)
        return self.scaled[key]

    def paste(self, image, name, xy, size=None, opacity=1.0):
        asset = self.sprite(name, size)
        if opacity != 1.0:
            key = ('opacity', name, size, opacity)
            if key not in self.scaled:
                adjusted = asset.copy()
                adjusted.putalpha(asset.getchannel('A').point(lambda a: int(a*opacity)))
                self.scaled[key] = adjusted
            asset = self.scaled[key]
        image.paste(asset, (int(round(xy[0])), int(round(xy[1]))), asset)

    def _text_run(self, text, size, bold=False):
        text = ''.join(c if 32 <= ord(c) <= 126 else '?' for c in str(text))
        style = 'bold' if bold else 'regular'
        sizes = self.fonts[style]['sizes']
        size_key = min(sizes, key=lambda k: abs(float(k)-float(size)))
        cache_key = (text, size_key, style)
        if cache_key in self.text_cache:
            self.text_cache.move_to_end(cache_key)
            return self.text_cache[cache_key]
        data = sizes[size_key]
        glyphs, pairs = data['glyphs'], data.get('kerning', {})
        cursor, places = 0.0, []
        min_x = min_y = 0
        max_x = max_y = 1
        previous = ''
        for char in text:
            cursor += pairs.get(previous+char, 0.0)
            glyph = glyphs[char]
            x = int(round(cursor+glyph['bearing_x']))
            y = int(glyph['bearing_y'])
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x+glyph['width']), max(max_y, y+glyph['height'])
            places.append((char, x, y))
            cursor += glyph['advance']
            previous = char
        mask = Image.new('L', (max_x-min_x, max_y-min_y), 0)
        atlas = self.assets[self.fonts[style]['path']]
        for char, x, y in places:
            glyph = glyphs[char]
            key = (style, size_key, char)
            if key not in self.glyph_cache:
                gx, gy = glyph['x'], glyph['y']
                self.glyph_cache[key] = atlas.crop((gx, gy, gx+glyph['width'], gy+glyph['height']))
            glyph_mask = self.glyph_cache[key]
            box = (x-min_x, y-min_y, x-min_x+glyph_mask.width, y-min_y+glyph_mask.height)
            # Kerning can overlap glyph rectangles. Preserve prior coverage as
            # FreeType does, rather than erasing it with the next glyph's zeros.
            mask.paste(ImageChops.lighter(mask.crop(box), glyph_mask), (box[0], box[1]))
        result = (mask, float(cursor), min_x, min_y)
        self.text_cache[cache_key] = result
        if len(self.text_cache) > 512:
            self.text_cache.popitem(last=False)
        return result

    def text(self, draw, xy, text, size=11, fill=WHITE, bold=False):
        mask, _, _, _ = self._text_run(text, size, bold)
        draw.bitmap((int(round(xy[0])), int(round(xy[1]))), mask, fill=fill)

    def red_draw_button(self, image):
        # Recolor the actual native button pixels, preserving its exact label,
        # shape, bevel and antialiasing. This never replaces it with a new UI.
        box=(275,218,319,234)
        original=image.crop(box)
        key=original.tobytes()
        if getattr(self,'_red_draw_key',None)!=key:
            red=original.copy()
            red.putdata([(max(r,g),round(g*.10),round(b*.15))
                         if r>=64 and g>=55 and min(r,g)>b*1.12
                         else (r,g,b) for r,g,b in original.getdata()])
            self._red_draw_key,self._red_draw_pixels=key,red
        image.paste(self._red_draw_pixels,box[:2])

    def manual_auto_mark(self,image):
        # A tiny filled M, close to the existing 3x4 speed triangles in size.
        if not hasattr(self,'_manual_auto_mark'):
            mask=Image.new('L',(5,4),0)
            mask.putdata([255 if pattern&(1<<(4-x)) else 0
                          for pattern in (0b10001,0b11011,0b10101,0b10001) for x in range(5)])
            self._manual_auto_mark=mask
        image.paste((0,0,0),(257,209),self._manual_auto_mark)
        image.paste(GOLD,(256,208),self._manual_auto_mark)

    def speed_triangle(self, image, x):
        # Supersampling keeps this tiny filled triangle readable on the LCD.
        # Cache its 3x4 coverage mask; no per-frame resizing is needed.
        if not hasattr(self, '_speed_triangle'):
            mask = Image.new('L', (24, 32), 0)
            ImageDraw.Draw(mask).polygon(((0, 0), (23, 15), (0, 31)), fill=255)
            mask = mask.resize((3, 4), getattr(Image, 'Resampling', Image).LANCZOS)
            peak = mask.getextrema()[1]
            self._speed_triangle = mask.point(lambda value: round(value*255/peak))
        image.paste(GOLD, (x, 208, x+3, 212), self._speed_triangle)

    def right(self, draw, right, y, text, size=11, fill=WHITE, bold=False):
        mask, _, _, _ = self._text_run(text, size, bold)
        self.text(draw, (right-mask.width, y), text, size, fill, bold)

    def center(self, draw, center, y, text, size=11, fill=WHITE, bold=False):
        mask, _, _, _ = self._text_run(text, size, bold)
        self.text(draw, (center-mask.width/2, y), text, size, fill, bold)

    def canvas_text(self, draw, x, y, text, size, fill=WHITE, bold=False, align='left'):
        # Fabric's top origin puts its alphabetic baseline one font-size below top.
        mask, advance, bx, by = self._text_run(text, size, bold)
        left = x-advance if align == 'right' else x-advance/2 if align == 'center' else x
        self.text(draw, (left+bx, y+float(size)+by), text, size, fill, bold)

    @staticmethod
    def source_card(card):
        if type(card) is not int or not 0 <= card < 52:
            raise ValueError('Card outside the 52-card deck')
        # Visually verified public deck: spades, clubs, hearts, diamonds.
        return (1, 3, 2, 0)[card//13]*13+card%13

    @staticmethod
    def base_box(snapshot):
        count=snapshot.get('max_hands',10)
        return (103,262) if count==3 else (108,268) if count==5 else (103,268)

    def card(self, card, width, height, held=False, selected=False, mini=False, disabled=False):
        # Focus/hold states never alter the exact face pixels.
        name = 'cards/'+str(self.source_card(card))+'.png' if card is not None else 'cards/Back_Disabled.png' if disabled else 'cards/Back.png'
        return self.sprite(name, (width, height))

    def fitted_label(self, image, box, label, size=8, fill=INK, bold=True):
        x0, y0, x1, y1 = box
        aw, ah = x1-x0+1, y1-y0+1
        if aw < 1 or ah < 1: raise ValueError('Label bounds must have positive area')
        mask = self._text_run(label, size, bold)[0]
        if mask.width > aw or mask.height > ah:
            mask = mask.resize((min(aw, mask.width), min(ah, mask.height)), getattr(Image, 'Resampling', Image).LANCZOS)
        left, top = x0+(aw-mask.width)//2, y0+(ah-mask.height)//2
        image.paste(fill, (left, top, left+mask.width, top+mask.height), mask)
        return left, top, left+mask.width-1, top+mask.height-1

    def pill(self, image, box, label, focused=False, disabled=False, size=8):
        # Offline-only utility dialogs; the casino controls below use real sprites.
        x0, y0, x1, y1 = box
        d = ImageDraw.Draw(image)
        d.rounded_rectangle(box, radius=6, fill=(132, 132, 143), outline=WHITE if focused else (162, 168, 186), width=1)
        d.rounded_rectangle((x0+2, y0+2, x1-2, y1-2), radius=4, fill=(214, 174, 13) if not disabled else (101, 98, 86))
        return self.fitted_label(image, (x0+4, y0+3, x1-4, y1-3), label, size, INK, True)

    def multiplier(self, image, index, current, following, opacity=1.0):
        x, y, width, height = self.HANDS[index]
        if following > 1:
            self.paste(image, 'multipliers/nexthand.png', (x-66, y+2), (25, 16), opacity)
            name = 'multipliers/'+str(following)+'x_2.png'
            asset = self.assets[name]
            size = (int(round(asset.width*16/asset.height)), 16)
            self.paste(image, name, (x-3-size[0], y+2), size, opacity)
        if current > 1:
            name = 'multipliers/'+str(current)+'x_2.png'
            asset = self.assets[name]
            size = (int(round(asset.width*24/asset.height)), 24)
            self.paste(image, name, (x-3-size[0], y+height-29), size, opacity)

    def win_indicator(self, image, index, result):
        category = result.get('category')
        if not result.get('payout') or category not in self.WIN_ART: return
        x, y, width, height = self.HANDS[index]
        cx, cy = x+width/2, y+.65*height
        self.paste(image, 'wins/payline'+str(self.WIN_ART[category])+'.png', (cx-65, cy-14), (130, 35))
        draw = ImageDraw.Draw(image)
        self.canvas_text(draw, cx, cy-4-11*.99/2, self.RESULT_LABELS[category], 11, WHITE, align='center')
        multiplier = int(result.get('multiplier', 1))
        payout = str(result['payout'])
        if multiplier > 1: payout = '%s X %s = %s' % (multiplier, result['base_payout'], result['payout'])
        self.canvas_text(draw, cx, cy+9-10*.99/2, payout, 10, (254, 254, 0), True, 'center')

    @staticmethod
    def _freeze(value):
        """Detach the cache key from every mutable level of an engine snapshot."""
        if isinstance(value, dict):
            return tuple((key, Renderer._freeze(value[key])) for key in sorted(value))
        if isinstance(value, (list, tuple)):
            return tuple(Renderer._freeze(item) for item in value)
        return value

    def _board_for(self, snapshot, selected_card, selected_hand):
        # Focus is a crisp native overlay. Moving it does not change any art.
        key = self._freeze({key: value for key, value in snapshot.items()
                            if key not in ('_badge_frame', '_button_focus')})
        if key != self._normal_key:
            self._normal_board = self._render_board(snapshot, selected_card, selected_hand)
            self._normal_key = key
            self._normal_native = None
            self._normal_badge = None
        return self._normal_board

    def _badge_name(self, snapshot):
        sequence = self.manifest['sequences']['active' if snapshot.get('feature', True) else 'inactive']
        return sequence['frames'][int(snapshot.get('_badge_frame', 0)) % len(sequence['frames'])]

    def render_source_uncached(self, snapshot, selected_card=0, selected_hand=0, menu=None):
        """Full logical composition, retained as the pixel-equivalence oracle."""
        if menu and menu.get('page') == 'paytable': return self.render_paytable_source(snapshot, menu)
        if menu and menu.get('page') == 'controls': return self.render_help_source(snapshot, menu)
        image = self._render_board(snapshot, selected_card, selected_hand)
        self.paste(image, self._badge_name(snapshot), (541, 257))
        return image

    def render_source(self, snapshot, selected_card=0, selected_hand=0, menu=None):
        if menu and menu.get('page') in ('paytable', 'controls'):
            return self.render_source_uncached(snapshot, selected_card, selected_hand, menu)
        image = self._board_for(snapshot, selected_card, selected_hand).copy()
        self.paste(image, self._badge_name(snapshot), (541, 257))
        return image

    def _render_board(self, snapshot, selected_card=0, selected_hand=0):
        """Compose everything except the isolated, animated badge rectangle."""
        image = self.background.copy()
        draw = ImageDraw.Draw(image)
        phase = snapshot.get('phase', 'ready')
        initial, held = snapshot.get('initial') or [], snapshot.get('held') or [False]*5
        hands, results = snapshot.get('hands') or [], snapshot.get('results') or []
        next_x = snapshot.get('multipliers') or [1]*10
        current_x = snapshot.get('active_multipliers') or [1]*10
        reveal, deal_reveal = int(snapshot.get('_reveal', 5)), int(snapshot.get('_deal_reveal', 5))
        active = int(snapshot.get('round_num_hands', snapshot.get('num_hands', 10))) if phase in ('hold', 'result') else int(snapshot.get('num_hands', 10))
        for index, (x, y, width, height) in enumerate(self.HANDS):
            enabled = index < active
            if phase == 'result' and index < len(hands):
                cards = [card if n < reveal or held[n] else None for n, card in enumerate(hands[index])]
            elif phase == 'hold' and len(initial) == 5 and enabled:
                cards = [card if (n < deal_reveal if index == 0 else held[n]) else None for n, card in enumerate(initial)]
            else: cards = [None]*5
            size, step = ((83, 119), 87) if index == 0 else ((56, 80), 20)
            for n, card in enumerate(cards):
                asset = self.card(card, *size, disabled=not enabled)
                image.paste(asset, (x+n*step, y), asset)
            following = int(next_x[index]) if phase == 'ready' or (phase == 'result' and reveal == 5) else 1
            current = int(current_x[index]) if phase != 'ready' and enabled else 1
            self.multiplier(image, index, current, following, 1.0 if enabled else .6)
            if enabled and phase == 'result' and reveal == 5 and index < len(results):
                self.win_indicator(image, index, results[index])
        for n, is_held in enumerate(held):
            if is_held and phase in ('hold', 'result'):
                self.paste(image, 'gui/hold.png', (103+41+87*n-24, 375))
        total_win = int(snapshot.get('total_win', 0)) if phase == 'result' else 0
        if total_win:
            self.canvas_text(draw, 106, 410, _short_number(total_win), 15, (255, 255, 0), True, 'right')
        self.canvas_text(draw, 167, 410, _short_number(snapshot.get('total_bet', 100)), 15, (255, 255, 0), True, 'right')
        self.canvas_text(draw, 630, 412, _short_number(snapshot.get('credits', 10000)), 16, (255, 255, 0), True, 'right')
        self.canvas_text(draw, 322, 422, snapshot.get('num_hands', 10), 15, (255, 255, 0), True, 'center')
        self.canvas_text(draw, 413, 422, snapshot.get('bet_per_hand', 10), 15, (255, 255, 0), True, 'center')
        self.paste(image, 'gui/speaker_3.png', (457, 405))
        insufficient = int(snapshot.get('credits', 0)) < int(snapshot.get('total_bet', 100))
        names = ('SeePaysHelp', 'MoreGames', 'Speed%02d' % (int(snapshot.get('_speed', 1))+1), 'SelectHands', 'BetPerHand', 'BetMax', 'Draw' if phase == 'hold' else 'Deal')
        for i, name in enumerate(names):
            disabled = ((phase == 'hold' and i in (3, 4, 5)) or (i == 3 and snapshot.get('bet_per_hand', 10) != 1) or (i == 5 and (insufficient or int(snapshot.get('credits', 0)) <= 0)) or (i == 6 and phase != 'hold' and insufficient))
            name = ('SpeedDim' if i == 2 else name+'Dim') if disabled else name
            self.paste(image, 'gui/'+name+'.png', (self.BUTTON_X[i], 437), (86, 30))
        self.canvas_text(draw, 318, 466, 'Double Dbl Bonus', 11, WHITE, align='center')
        if phase == 'result' and reveal == 5:
            self.canvas_text(draw, 15, 467, 'Game Over', 10, WHITE)
        return image

    def render(self, snapshot, selected_card=0, selected_hand=0, menu=None):
        if menu and menu.get('page') not in ('paytable', 'controls'):
            image = Image.new('RGB', (WIDTH, HEIGHT), BG)
            self.render_menu(image, snapshot, menu)
            return image
        lanczos = getattr(Image, 'Resampling', Image).LANCZOS
        if menu:
            source = self.render_source(snapshot, selected_card, selected_hand, menu)
            return source.resize((WIDTH, HEIGHT), lanczos).convert('RGB')
        board = self._board_for(snapshot, selected_card, selected_hand)
        badge = self._badge_name(snapshot)
        if self._normal_native is None:
            source = board.copy()
            self.paste(source, badge, (541, 257))
            self._normal_native = source.resize((WIDTH, HEIGHT), lanczos).convert('RGB')
        elif badge != self._normal_badge:
            # Downsampling by two gives LANCZOS a six-source-pixel support.
            # The dirty native rectangle includes that halo; the source crop
            # includes a second halo so its own filter edge cannot affect it.
            # Even crop coordinates keep the original half-pixel sampling grid.
            source_box = (528, 244, 640, 396)
            patch = board.crop(source_box)
            self.paste(patch, badge, (541-source_box[0], 257-source_box[1]))
            patch = patch.resize((56, 76), lanczos)
            self._normal_native.paste(patch.crop((3, 3, 56, 73)), (267, 125))
        self._normal_badge = badge
        # The caller may draw notices or otherwise mutate its returned frame.
        image = self._normal_native.copy()
        self._draw_focus(image, snapshot, selected_card)
        return image

    def render_uncached(self, snapshot, selected_card=0, selected_hand=0, menu=None):
        """Full native composition for cache and filtering equivalence checks."""
        if menu and menu.get('page') not in ('paytable', 'controls'):
            image = Image.new('RGB', (WIDTH, HEIGHT), BG)
            self.render_menu(image, snapshot, menu)
            return image
        source = self.render_source_uncached(snapshot, selected_card, selected_hand, menu)
        image = source.resize((WIDTH, HEIGHT), getattr(Image, 'Resampling', Image).LANCZOS).convert('RGB')
        if not menu:
            self._draw_focus(image, snapshot, selected_card)
        return image

    def _draw_focus(self, image, snapshot, selected_card):
        """High-contrast hardware focus, deliberately drawn after downsampling."""
        draw = ImageDraw.Draw(image)
        focus = snapshot.get('_button_focus')
        if focus is not None:
            index = max(0, min(6, int(focus)))
            left = int(math.floor(self.BUTTON_X[index]/2.0))
            right = int(math.ceil((self.BUTTON_X[index]+86)/2.0))-1
            footer = image.crop((0, 233, WIDTH, HEIGHT))
            draw.rounded_rectangle((left-1, 217, right+1, 233), radius=6,
                                   outline=(0, 0, 0), width=3)
            draw.rounded_rectangle((left, 218, right, 232), radius=5,
                                   outline=WHITE, width=2)
            # The footer is immediately adjacent to the controls. Preserve its
            # caption and antialiasing exactly instead of painting a halo on it.
            image.paste(footer, (0, 233))
        elif snapshot.get('phase') == 'hold':
            index = max(0, min(4, int(selected_card)))
            base_x,base_y=self.base_box(snapshot)
            top=base_y//2
            source_left = base_x+87*index
            left = int(math.floor(source_left/2.0))
            right = int(math.ceil((source_left+83)/2.0))-1
            center = int(round((source_left+41)/2.0))
            held = snapshot.get('held') or [False]*5
            # The real HELD tag overlaps the card's bottom edge. Keep its native
            # pixels and filtering halo unobscured by the new focus ring.
            held_box = (center-15, 184, center+15, 202) if held[index] else None
            held_pixels = image.crop(held_box) if held_box else None
            draw.rounded_rectangle((left-2, top-3, right+2, top+62), radius=3,
                                   outline=(0, 0, 0), width=4)
            draw.rounded_rectangle((left-1, top-2, right+1, top+61), radius=2,
                                   outline=GOLD, width=2)
            draw.polygon(((center-6, top-10), (center+6, top-10), (center, top-1)), fill=(0, 0, 0))
            draw.polygon(((center-5, top-9), (center+5, top-9), (center, top-2)), fill=GOLD)
            draw.line((left+4, top-2, right-4, top-2), fill=WHITE, width=1)
            if held_pixels is not None:
                image.paste(held_pixels, held_box[:2])

    def render_help_source(self, snapshot, menu):
        image = Image.new('RGB', self.SOURCE_SIZE, (0, 0, 160))
        holding = snapshot.get('phase') == 'hold'
        count = 2 if holding else 4
        index = max(0, min(count-1, int(menu.get('index', 0))))
        self.paste(image, 'help/'+('helpdraw' if holding else 'helpscreen')+str(index+1)+'.png', (20, 24))
        if index > 0: self.paste(image, 'help/shared/prev-page.png', (260, 382))
        if index < count-1: self.paste(image, 'help/shared/next-page.png', (370, 382))
        self.paste(image, 'help/shared/exit-help.png', (480, 382))
        return image

    def render_paytable_source(self, snapshot, menu):
        image = self.assets['backgrounds/uxpaytablebg.png'].convert('RGB')
        draw = ImageDraw.Draw(image)
        bet = int(menu.get('bet', 1))
        if bet not in (1, 2, 3, 4, 5, 10): bet = 1
        columns = ((225, 74), (297, 74), (369, 74), (441, 74), (514, 122))
        for n, (left, width) in enumerate(columns, 1):
            draw.rectangle((left+2, 1, left+width-5, 188), fill=(176, 0, 0) if n == min(bet, 5) else (0, 1, 68))
        draw.rectangle((374, 198, 490, 385), fill=(176, 0, 0) if bet == 10 else (0, 1, 68))
        size, step = 13.076923, 13.076923+13.076923/13
        for row, (category, pay, multiplier) in enumerate(PAYS[:-1]):
            label = self.PAY_LABELS.get(category, self.RESULT_LABELS[category].upper())
            bold = self._text_run(label, size, True)[1] <= 214
            label_width = self._text_run(label, size, bold)[1]
            dots = max(0, int(math.ceil((219-label_width)/self._text_run('.', size, True)[1]))-1)
            label += '.'*dots
            self.canvas_text(draw, 6.5, 2.3+row*step, label, size, (255, 255, 0), bold)
            self.canvas_text(draw, 149.5, 199+row*step, label, size, (255, 255, 0), bold)
            for coin, right in enumerate((291, 363, 435, 507, 631), 1):
                award = (800 if coin == 5 else 250)*coin if category == 'royal_flush' else pay*coin
                self.canvas_text(draw, right, 2.3+row*step, award, size, (255, 255, 0), True, 'right')
            self.canvas_text(draw, 487, 199+row*step, str(multiplier)+'X', size, (255, 255, 0), True, 'right')
        self.canvas_text(draw, 314, 410, 'BET', 19, WHITE, True)
        self.canvas_text(draw, 357, 410, bet, 19, WHITE, True)
        self.paste(image, 'help/buttons/help.png', (1, 440))
        if bet > 1: self.paste(image, 'help/buttons/betdown.png', (341, 440))
        if bet < 10: self.paste(image, 'help/buttons/betup.png', (440, 440))
        self.paste(image, 'help/buttons/return.png', (548, 440))
        return image

    def render_menu(self, image, snapshot, menu):
        d = ImageDraw.Draw(image)
        page = menu.get('page', 'options')
        d.rectangle((0, 0, 319, 239), fill=BG)
        d.rounded_rectangle((8, 12, 312, 219), radius=3, fill=(0, 0, 0), outline=(175, 175, 190), width=2)
        title = {'controls': 'POKER HELP', 'reset_confirm': 'NEW SESSION?',
                 'more_games': 'DOUBLE DOUBLE BONUS', 'hands': 'SELECT HANDS',
                 'options': 'GAME OPTIONS', 'inspect': 'RESULT DETAILS'}.get(page, 'POKER HELP')
        d.rectangle((70, 13, 250, 29), fill=(175, 175, 180))
        self.center(d, 160, 16, title, 12, INK, True)
        if page == 'inspect':
            index = max(0, min(9, int(menu.get('index', 0))))
            results = snapshot.get('results') or []
            hands = snapshot.get('hands') or []
            self.center(d, 160, 42, 'HAND '+str(index+1), 14, GOLD, True)
            if index < len(hands):
                for i, card in enumerate(hands[index]):
                    image.paste(self.card(card, 49, 69), (21+i*57, 67))
            if index < len(results):
                result = results[index]
                self.center(d, 160, 146, LABELS.get(result.get('category'), ''), 14, GOLD, True)
                self.center(d, 160, 167, 'WIN '+str(result.get('payout', 0))+'  NOW '+str(result.get('multiplier', 1))+'X  NEXT '+str(result.get('next_multiplier', 1))+'X', 11, WHITE, True)
            self.center(d, 160, 196, 'UP/DOWN HAND   K3 RETURN', 11, MUTED)
        elif page == 'reset_confirm':
            self.center(d, 160, 66, 'Reset free credits and clear multipliers?', 12, WHITE)
            self.center(d, 160, 92, 'MIDDLE: NEW SESSION', 13, GOLD, True)
            self.center(d, 160, 119, 'TOP: ADD 10,000 (KEEP X)', 12, GREEN, True)
            self.center(d, 160, 149, 'K3: RETURN TO GAME', 12, WHITE)
        elif page == 'more_games':
            self.center(d, 160, 64, '9/6 DOUBLE DOUBLE BONUS', 15, GOLD, True)
            self.center(d, 160, 94, 'This build contains this game only.', 12, WHITE)
            self.pill(image, (79, 126, 241, 149), 'ADD 10,000 CREDITS', True, size=11)
            self.center(d, 160, 171, 'EITHER MIDDLE: add credits, keep X', 10, WHITE)
            self.center(d, 160, 193, 'K3: RETURN TO GAME', 10, MUTED)
        elif page == 'hands':
            self.center(d, 160, 70, '10 HANDS SELECTED', 19, GOLD, True)
            self.center(d, 160, 104, 'Nine upper hands plus the base hand.', 11, WHITE)
            self.center(d, 160, 139, 'This image is configured for Ten Play.', 11, WHITE)
            self.center(d, 160, 190, 'K3: RETURN TO GAME', 11, MUTED)
        else:
            index = int(menu.get('index', 0)) % len(OPTIONS)
            for row, option in enumerate(OPTIONS):
                y = 46+row*26
                if option == 'BONUS BET':
                    option += ': ' + ('ON' if snapshot.get('feature', True) else 'OFF')
                    if snapshot.get('phase') == 'hold': option += ' (IN HAND)'
                self.pill(image, (24, y, 296, y+21), option, focused=(row == index), size=12)
            self.center(d, 160, 184, 'OFF collects earned X; earns no new X.', 10, MUTED)
            self.center(d, 160, 202, 'UP/DN SELECT  MIDDLE OPEN  K3 BACK', 10, WHITE)



class PokerUI:
    """Debounced action controller with short, nonblocking visual sequences.

    The engine settles atomically; animation only presents detached snapshots.
    Fresh DOWN during a draw result presentation advances to the next deal.
    During a deal presentation it only reveals; held input never repeats.
    """
    SPEEDS = (0.13, 0.065, 0.0)
    UP_CLICK_GAP_SECONDS = 0.35
    AUTOPLAY_UP_CLICKS = 3
    HINT_HOLD_SECONDS = 0.30
    HINT_DRAW_FLASH_SECONDS = 1.0
    UP_MASK = 1
    AUTO_CONSIDER_SECONDS = 3.2
    AUTO_SELECT_SECONDS = 0.24
    AUTO_HOLD_SECONDS = 0.28
    AUTO_RESULT_SECONDS = 1.35
    AUTO_PROFILES = (
        dict(name='manual', consider=1.6, select=0.12, draw=0.15, result=0.8, animation=0.04, manual=True, instant=True),
        dict(name='medium', consider=3.2, select=0.24, draw=0.28, result=1.35, animation=0.065),
        dict(name='fast', consider=1.6, select=0.12, draw=0.15, result=0.8, animation=0.04),
    )
    UP_TAP_COMMIT_GRACE_SECONDS = 0.02

    def __init__(self, session=None, width=WIDTH, height=HEIGHT, font_dir=None, clock=time.monotonic, advisor=None, cabinet=None):
        if (width, height) != (WIDTH, HEIGHT):
            raise ValueError('Poker requires the Play/Plus 320x240 display')
        self.cabinet = (session is None) if cabinet is None else bool(cabinet)
        self._cabinet_bank = None
        self._cabinet_game_over = False
        if session is None:
            from poker_engine import Session
            session = Session(game_id='bp3') if self.cabinet else Session()
        self.session = session
        if self.cabinet or session.snapshot().get('max_hands',10)!=10 or session.snapshot().get('game_id','ddb10')!='ddb10':
            from poker_cabinet_ui import CabinetRenderer,GameBank
            self.renderer=CabinetRenderer(font_dir)
            if self.cabinet:self._cabinet_bank=GameBank()
        else:self.renderer = Renderer(font_dir)
        self.selected_card = 0
        self.selected_hand = 0
        self.menu = {'page':'cabinet','index':0,'return':False} if self.cabinet else None
        self.notice = None
        self._credit_notice = False
        self._entropy_notice = False
        self._retry_max_bet = False
        self.button_focus = None
        self.speed = 1
        self.pay_preview_bet = self.session.bet_per_hand if self.cabinet else 1
        self._clock = clock
        self._animation = None
        self._visual = None
        self._last_stage = None
        self._badge_started = self._clock()
        self._badge_feature = bool(self.session.snapshot()['feature'])
        self._badge_frame = 0
        self._advisor = advisor
        self._advisor_token = None
        self._advisor_board = None
        self._advice = None
        self._up_held = False
        self._up_held_since = None
        self._peek_ready = False
        self._draw_hint_started = None
        self._draw_hint_step = None
        self._hint_failed_key = None
        self._last_up = None
        self._up_click_count = 0
        self._manual_up_due = None
        self._manual_hold_key = None
        self._peek_blocked_until_release = False
        self._captured_input_at = None
        self.autoplay = False
        self._auto_stage = None
        self._auto_due = None
        self._auto_index = None
        self.autoplay_speed = 0
        self._manual_auto_draw_requested = False
        self._manual_retry_action = self._manual_retry_due = None
        self._auto_up_edge = self._auto_up_pause_at = self._auto_up_due = None
        self._closed = False

    @property
    def manual_autoplay(self):
        return self.autoplay and bool(self.AUTO_PROFILES[self.autoplay_speed].get('manual'))

    @property
    def autoplay_display_speed(self):
        return 2 if self.manual_autoplay else self.autoplay_speed

    def set_pressed_mask_sampled(self, mask, captured_at):
        if type(captured_at) not in (int, float) or not math.isfinite(captured_at):
            raise ValueError('Invalid sampled input time')
        return self.set_pressed_mask(mask, captured_at)

    def set_pressed_mask(self, mask, captured_at=None):
        """Apply current stable GPIO state before dispatching queued edges.

        A released UP edge may arrive late after drawing. It can contribute to
        a sampled-time triple press, but can never leave a stale hint visible.
        """
        if self._closed:
            return False
        if type(mask) is not int or not 0 <= mask < 256:
            raise ValueError('Invalid pressed button mask')
        held = bool(mask & self.UP_MASK)
        was_visible = self.hint_visible
        if not held:
            self._peek_blocked_until_release = False
        if held == self._up_held:
            return False
        self._up_held = held
        self._up_held_since = (self._clock() if captured_at is None else captured_at) if held else None
        self._peek_ready = False
        self._draw_hint_started = self._draw_hint_step = None
        self._hint_failed_key = None
        if not held:
            # Release hides the peek immediately, but the detached calculation
            # belongs to this dealt hand. Do not cancel cold table loading on
            # the first release of a double/triple tap.
            return was_visible
        return False

    @property
    def hint_visible(self):
        if (not self._up_held or not self._peek_ready or self._peek_blocked_until_release
                or self.autoplay or self.menu is not None
                or self.button_focus is not None or self.notice or self._animation is not None
                or self._advice is None):
            return False
        state = self.session.snapshot()
        return state['phase'] == 'hold' and self._advisor_board == self._advice_key(state)

    def handle_sampled(self, action, captured_at):
        """Keep gesture timing tied to GPIO edges through a slow LCD update."""
        if type(captured_at) not in (int, float) or not math.isfinite(captured_at):
            raise ValueError('Invalid sampled input time')
        previous = self._captured_input_at
        self._captured_input_at = captured_at
        try:
            # Preserve subclasses' action logging and the ordinary public API.
            return self.handle(action)
        finally:
            self._captured_input_at = previous

    def handle(self, action):
        action = str(action).upper()
        if self._closed or action not in ('LEFT', 'RIGHT', 'UP', 'DOWN', 'CENTER', 'KEY1', 'KEY2', 'KEY3'):
            return False
        if self.autoplay:
            if action == 'UP':
                return self._handle_autoplay_up()
            if action == 'DOWN' and self.manual_autoplay:
                return self._manual_autoplay_down()
            # The stop click never also deals, toggles a hold, or opens a menu.
            self.pause_autoplay()
            self._peek_blocked_until_release = self._up_held
            return True
        main_board = self.menu is None and self.button_focus is None
        if main_board and action == 'UP':
            return self._handle_up()
        # Cancellation precedes the manual action. A queued solver answer can
        # never reapply holds after the user has taken control or opened a menu.
        self.pause_autoplay()
        if self.notice and action in ('DOWN', 'CENTER', 'KEY2') and self._credit_notice:
            self.session.add_credits()
            self._clear_notice()
            return True
        if self.notice and action in ('DOWN', 'CENTER', 'KEY2') and self._entropy_notice:
            retry_max_bet = self._retry_max_bet
            self._clear_notice()
            self._play(max_bet=retry_max_bet)
            return True
        self._clear_notice()
        if self._animation is not None:
            if (action == 'DOWN' and self._animation['kind'] == 'draw'
                    and self.session.snapshot()['phase'] == 'result'):
                # Draw already settled atomically. A fresh DOWN press means
                # next Deal even while its result presentation is running.
                self._finish_animation()
                return self._play()
            if action in ('DOWN', 'CENTER', 'KEY1', 'KEY2', 'KEY3'):
                self._finish_animation()
                if action == 'KEY3': self.button_focus = 0
            return True
        if self.menu is not None:
            return self._menu_action(action)
        if self.button_focus is not None:
            if action == 'KEY3':
                self.button_focus = None
            elif action in ('LEFT', 'UP', 'RIGHT', 'DOWN'):
                self.button_focus = (self.button_focus + (-1 if action in ('LEFT', 'UP') else 1)) % len(BUTTONS)
            elif action in ('CENTER', 'KEY1', 'KEY2'):
                return self._button_action(self.button_focus)
            return True
        if action == 'KEY3':
            self.button_focus = 0
        elif action in ('LEFT', 'RIGHT'):
            self.selected_card = (self.selected_card + (-1 if action == 'LEFT' else 1)) % 5
        elif action in ('CENTER', 'KEY1', 'KEY2'):
            phase = self.session.snapshot()['phase']
            if phase == 'hold':
                self.session.toggle_hold(self.selected_card)
            elif phase == 'result':
                if action in ('CENTER', 'KEY2'):
                    self._play()
                else:
                    self.menu = {'page': 'inspect', 'index': self.selected_hand}
        elif action == 'DOWN':
            self._play()
        return True

    def _clear_notice(self):
        self.notice = None
        self._credit_notice = self._entropy_notice = False
        self._retry_max_bet = False

    @staticmethod
    def _advice_key(snapshot):
        return (snapshot.get('game_id','ddb10'), snapshot.get('phase'), tuple(snapshot.get('initial', ())),
                tuple(snapshot.get('active_multipliers', ())),
                snapshot.get('round_feature'), snapshot.get('round_base_bet'),
                snapshot.get('round_num_hands'), snapshot.get('rounds'))

    def _get_advisor(self):
        if self._advisor is None:
            from poker_cabinet_strategy import CabinetAdvisor
            self._advisor = CabinetAdvisor()
        return self._advisor

    def _cancel_advice(self):
        had_advice = self._advisor_token is not None or self._advice is not None
        self._advisor_token = self._advisor_board = self._advice = None
        if had_advice and self._advisor is not None:
            try:
                self._advisor.cancel()
            except Exception:
                pass
        return had_advice

    def pause_autoplay(self):
        changed = self.autoplay or self._advisor_token is not None or self._advice is not None
        self._resume_autoplay_clock()
        self._clear_auto_up()
        self._peek_blocked_until_release = self._peek_blocked_until_release or self._up_held
        self.autoplay = False
        self._manual_auto_draw_requested = False
        self._clear_manual_retry()
        self._auto_stage = self._auto_due = self._auto_index = None
        self._last_up = None
        self._up_click_count = 0
        self._manual_up_due = None
        self._manual_hold_key = None
        return self._cancel_advice() or changed

    def on_input_reset(self):
        """Discard stale input without removing the selected autoplay mode.

        The sampler still requires a fresh neutral release. M waits at a Deal
        or Draw boundary, so retaining that idle mode cannot replay a press.
        Continuous playback is already intentional; preserve its progress and
        advice rather than treating sampling recovery as a physical stop key.
        """
        if self._closed:
            return False
        if not self.autoplay:
            # Discard gesture/action state, not a read-only first-hand preload.
            # A recovered neutral sample cannot apply a hold, draw, or show red.
            changed = self._up_click_count != 0 or self._manual_hold_key is not None or self.hint_visible
            self._last_up = self._manual_up_due = self._manual_hold_key = None
            self._up_click_count = 0
            self._peek_ready = False
            self._peek_blocked_until_release = self._up_held
            self._draw_hint_started = self._draw_hint_step = None
            return changed
        if self.autoplay and not self.manual_autoplay:
            self._resume_autoplay_clock()
            self._clear_auto_up()
            return True
        manual = self.manual_autoplay
        changed = self.pause_autoplay()
        if manual:
            self.autoplay_speed = 0
            self.autoplay = True
            self._finish_animation()
            self._auto_stage = 'manual-draw' if self.session.snapshot()['phase'] == 'hold' else 'manual-deal'
        return changed

    def _clear_manual_retry(self):
        if self._manual_retry_action is not None and self._entropy_notice:
            self._clear_notice()
        self._manual_retry_action = self._manual_retry_due = None

    def _wait_for_manual_random(self, action, now):
        if not self.manual_autoplay or not self._entropy_notice:
            return False
        # Own only the already requested operation. A secure-RNG wait cannot
        # spend or settle anything, and repeated DOWN presses never queue bets.
        self._manual_retry_action = action
        self._manual_retry_due = now + .10
        return True

    def _retry_manual_random(self, now):
        action = self._manual_retry_action
        phase = self.session.snapshot()['phase']
        if ((action == 'deal' and phase not in ('ready', 'result')) or
                (action == 'draw' and phase != 'hold') or not self._entropy_notice):
            return self.pause_autoplay()
        if now < self._manual_retry_due:
            return False
        self._clear_notice()
        self._play()
        if self.notice:
            if not self._wait_for_manual_random(action, now):
                self.pause_autoplay()
        else:
            self._clear_manual_retry()
            self._auto_stage = 'manual-draw' if action == 'deal' else 'manual-deal'
            self._auto_due = None
            if action == 'deal':
                self._request_hint(now)
        return True

    def _wants_manual_advice(self):
        return (self._manual_hold_key is not None or
                (not self.autoplay and self._manual_up_due is not None
                 and self._up_click_count == 2))

    def _commit_manual_up(self):
        choose_holds = self._up_click_count == 2
        self._manual_up_due = self._last_up = None
        self._up_click_count = 0
        state = self.session.snapshot()
        if choose_holds and state['phase'] == 'hold':
            self._manual_hold_key = self._advice_key(state)
        return False

    def _apply_manual_hold(self):
        if self._manual_hold_key is None:
            return False
        state = self.session.snapshot()
        if (self.autoplay or self._advice_key(state) != self._manual_hold_key
                or self.menu is not None or self.button_focus is not None or self.notice):
            self._manual_hold_key = None
            return self._cancel_advice()
        if self._animation is not None or self._advice is None:
            return False
        if self._advisor_board != self._manual_hold_key:
            return False
        mask = self._advice['mask']
        self._manual_hold_key = None
        for index, held in enumerate(state['held']):
            if held != bool(mask & (1 << index)):
                self.session.toggle_hold(index)
        if not self._up_held:
            self._cancel_advice()
        return True

    def _clear_auto_up(self):
        self._auto_up_edge = self._auto_up_pause_at = self._auto_up_due = None
        self._last_up = None
        self._up_click_count = 0

    def _handle_autoplay_up(self):
        now = self._clock()
        edge = now if self._captured_input_at is None else self._captured_input_at
        if self._last_up is not None and edge < self._last_up:
            return True
        consecutive = self._last_up is not None and edge-self._last_up <= self.UP_CLICK_GAP_SECONDS
        if self._auto_up_edge is not None and not consecutive:
            self._commit_auto_up()
        if self._auto_up_edge is None:
            self._auto_up_edge = edge
            self._auto_up_pause_at = now
        self._up_click_count += 1
        self._last_up = edge
        self._auto_up_due = edge+self.UP_CLICK_GAP_SECONDS+self.UP_TAP_COMMIT_GRACE_SECONDS
        if self._up_click_count == self.AUTOPLAY_UP_CLICKS:
            # The third click stops autoplay before its double-click prefix
            # can change speed. Single/held UP still never acts as a stop key.
            return self.pause_autoplay()
        return True

    def _commit_auto_up(self):
        changed = self._up_click_count == 2
        if changed:
            self._cycle_autoplay_speed()
        self._resume_autoplay_clock()
        self._clear_auto_up()
        return changed

    def _resume_autoplay_clock(self):
        if self._auto_up_pause_at is None:
            return
        paused = max(0.0, self._clock()-self._auto_up_pause_at)
        if self._auto_due is not None:
            self._auto_due += paused
        if self._animation is not None:
            self._animation['started'] += paused

    def _cycle_autoplay_speed(self):
        self._clear_manual_retry()
        old=self.AUTO_PROFILES[self.autoplay_speed]
        self.autoplay_speed=(self.autoplay_speed+1)%len(self.AUTO_PROFILES)
        new=self.AUTO_PROFILES[self.autoplay_speed]
        anchor=self._auto_up_pause_at if self._auto_up_pause_at is not None else self._clock()
        self._manual_auto_draw_requested=False
        phase=self.session.snapshot()['phase']
        if new.get('manual'):
            self._finish_animation()
            self._auto_stage='manual-draw' if phase=='hold' else 'manual-deal'
            self._auto_due=self._auto_index=None
            return
        if old.get('manual'):
            self._auto_stage='consider' if phase=='hold' else 'result' if phase=='result' else 'deal'
            self._auto_due=None if phase=='hold' else anchor+new['result'] if phase=='result' else anchor
            self._auto_index=None
            return
        key={'consider':'consider','select':'select','draw':'draw','result':'result'}.get(self._auto_stage)
        if key is not None and self._auto_due is not None:
            remaining=max(0.0,min(1.0,(self._auto_due-anchor)/old[key]))
            self._auto_due=anchor+remaining*new[key]
        if self._animation is not None:
            animation=self._animation
            progress=max(0.0,(anchor-animation['started'])/animation['interval'])
            animation['interval']=new['animation']
            animation['started']=anchor-progress*new['animation']
            self._last_stage=None

    def _manual_autoplay_down(self):
        self._resume_autoplay_clock()
        self._clear_auto_up()
        if self._manual_retry_action is not None:
            return True
        phase=self.session.snapshot()['phase']
        self._finish_animation()
        if phase in ('ready','result'):
            self._begin_autoplay_deal(self._clock())
        elif phase=='hold':
            # Advice is normally ready while the player studies the cards.
            # A cold solver queues exactly this draw, never a following deal.
            self._auto_stage='manual-draw'
            self._manual_auto_draw_requested=True
            self._poll_advice(self._clock())
            self._apply_manual_autoplay_draw(self._clock())
        return True

    def _begin_autoplay_deal(self,now):
        self._cancel_advice()
        self._manual_auto_draw_requested=False
        self._auto_index=None
        self._play()
        if self.notice:
            if not self._wait_for_manual_random('deal', now):
                self.pause_autoplay()
        elif self.session.snapshot()['phase']=='hold':
            self._auto_stage='manual-draw' if self.manual_autoplay else 'consider'
            self._auto_due=None
            self._request_hint(now)
        else:
            self._auto_stage,self._auto_due='manual-deal' if self.manual_autoplay else 'result-animation',None

    def _apply_manual_autoplay_draw(self,now):
        if not self.manual_autoplay or not self._manual_auto_draw_requested:
            return False
        state=self.session.snapshot()
        if state['phase']!='hold':
            return self.pause_autoplay()
        if self._advice is None:
            return self._request_hint(now)
        if self._advisor_board!=self._advice_key(state):
            return self.pause_autoplay()
        mask=self._advice['mask']
        for index,held in enumerate(state['held']):
            if held!=bool(mask&(1<<index)):
                self.session.toggle_hold(index)
        self._manual_auto_draw_requested=False
        self._auto_index=None
        self._play()
        if self.notice:
            if not self._wait_for_manual_random('draw', now):
                self.pause_autoplay()
        else:
            self._auto_stage,self._auto_due='manual-deal',None
        return True

    def close(self):
        if self._closed:
            return
        self.pause_autoplay()
        if self._advisor is not None:
            # Failure must reach the launcher: entering the signer while an
            # advice worker is still alive would violate the shutdown boundary.
            self._advisor.close()
        self._closed = True

    def _strategy_failed(self):
        failed_key = self._advisor_board or self._advice_key(self.session.snapshot())
        last_up = self._last_up
        click_count = self._up_click_count
        self.pause_autoplay()
        self._last_up = last_up
        self._up_click_count = click_count
        # A failed peek stays silent and does not spin up another request every
        # frame. Releasing and pressing UP again permits an explicit retry.
        self._hint_failed_key = failed_key
        return True

    def _request_hint(self, now, prepare=False):
        state = self.session.snapshot()
        if state['phase'] != 'hold' or (not prepare and not self.autoplay and
                (not self._wants_manual_advice() and
                 (not self._up_held or self._peek_blocked_until_release))):
            return False
        key = self._advice_key(state)
        if not self.autoplay and key == self._hint_failed_key:
            return False
        if key == self._advisor_board and (self._advisor_token is not None or self._advice is not None):
            return False
        self._cancel_advice()
        try:
            advisor = self._get_advisor()
            token = advisor.request(state)
            if token is None:
                raise ValueError('Missing advice request token')
        except Exception:
            return self._strategy_failed()
        self._advisor_board, self._advisor_token = key, token
        return True

    def _handle_up(self):
        now = self._clock()
        edge_time = now if self._captured_input_at is None else self._captured_input_at
        consecutive = (self._last_up is not None and
                       0 <= edge_time-self._last_up <= self.UP_CLICK_GAP_SECONDS)
        if self._manual_up_due is not None and not consecutive:
            self._commit_manual_up()
        self._up_click_count = self._up_click_count+1 if consecutive else 1
        self._last_up = edge_time
        self._manual_up_due = edge_time+self.UP_CLICK_GAP_SECONDS+self.UP_TAP_COMMIT_GRACE_SECONDS
        if self._up_click_count == self.AUTOPLAY_UP_CLICKS:
            self._last_up = None
            self._up_click_count = 0
            self._manual_up_due = self._manual_hold_key = None
            self._clear_notice()
            self.autoplay_speed = 0
            self.autoplay = True
            phase = self.session.snapshot()['phase']
            self._manual_auto_draw_requested=False
            if self.manual_autoplay:
                self._finish_animation()
                self._auto_stage='manual-draw' if phase=='hold' else 'manual-deal'
                self._auto_due=None
            else:
                self._auto_stage = 'consider' if phase == 'hold' else ('result-animation' if phase == 'result' else 'deal')
                self._auto_due = None if phase == 'hold' else now
            self._auto_index = None
            if phase == 'hold': self._request_hint(now)
            return True
        if self._animation is None and self.notice is None:
            return self._request_hint(now)
        return False

    def _poll_advice(self, now):
        # Advice may finish before UP is pressed or after it is released.
        # Visibility and hold application have separate, explicit gesture gates.
        if self._advisor_board is not None and self._advisor_board != self._advice_key(self.session.snapshot()):
            self.pause_autoplay()
            return True
        if self._advisor_token is None:
            return False
        token = self._advisor_token
        try:
            answer = self._advisor.poll(token)
        except Exception:
            return self._strategy_failed()
        if answer is None:
            return False
        if not isinstance(answer, dict) or answer.get('error'):
            return self._strategy_failed()
        # A service may include its token for additional stale-response checks.
        if answer.get('token', token) != token:
            return False
        mask = answer.get('mask')
        if type(mask) is not int or not 0 <= mask < 32:
            return self._strategy_failed()
        self._advisor_token = None
        self._advice = dict(answer)
        return True

    def _update_autoplay(self, now):
        if not self.autoplay:
            return False
        if self.manual_autoplay and self._manual_retry_action is not None:
            if self.menu is not None or self.button_focus is not None:
                return self.pause_autoplay()
            return self._retry_manual_random(now)
        if self.menu is not None or self.button_focus is not None or self.notice:
            return self.pause_autoplay()
        if self._animation is not None:
            return False
        state = self.session.snapshot()
        phase = state['phase']
        stage = self._auto_stage
        profile = self.AUTO_PROFILES[self.autoplay_speed]
        if stage == 'result-animation':
            self._auto_stage,self._auto_due = ('manual-deal',None) if self.manual_autoplay else ('result',now+profile['result'])
            return True
        if stage == 'manual-deal':
            return False
        if stage == 'manual-draw':
            if not self._manual_auto_draw_requested:
                return self._request_hint(now)
            return self._apply_manual_autoplay_draw(now)
        if stage in ('deal', 'result'):
            if self.manual_autoplay:
                self._auto_stage,self._auto_due='manual-deal',None
                return True
            if now < self._auto_due:
                return False
            self._begin_autoplay_deal(now)
            return True
        if stage == 'consider':
            if phase != 'hold':
                self.pause_autoplay()
                return True
            if self._auto_due is None:
                # The study pause starts only after the full deal reveal,
                # independent of animation SPEED or advisor completion time.
                self._auto_due = now+profile['consider']
                return True
            if self._advice is None and self._advisor_token is None:
                return self._request_hint(now)
            if now < self._auto_due:
                return False
            if self._advice is None:
                return False
            if phase != 'hold' or self._advisor_board != self._advice_key(state) or self._advice is None:
                self.pause_autoplay()
                return True
            self.selected_card = self._auto_index = 0
            self._auto_stage, self._auto_due = 'select', now+profile['select']
            return True
        if stage == 'select':
            if now < self._auto_due:
                return False
            if phase != 'hold' or self._advisor_board != self._advice_key(state) or self._advice is None:
                self.pause_autoplay()
                return True
            index = self._auto_index
            if state['held'][index] != bool(self._advice['mask'] & (1 << index)):
                self.session.toggle_hold(index)
            if index == 4:
                self._auto_stage, self._auto_due = 'draw', now+profile['draw']
            else:
                self._auto_index = self.selected_card = index+1
                # Never catch up multiple card selections after a slow frame.
                self._auto_due = now+profile['select']
            return True
        if stage == 'draw':
            if now < self._auto_due:
                return False
            if phase != 'hold':
                self.pause_autoplay()
                return True
            self._cancel_advice()
            self._play()
            if self.notice:
                self.pause_autoplay()
            else:
                self._auto_stage = 'result-animation'
            return True
        return False

    handle_action = handle

    def _play(self, max_bet=False):
        before = self.session.snapshot()
        self._cancel_advice()
        try:
            if before['phase'] == 'hold':
                if max_bet: return False
                self.session.draw()
                kind = 'draw'
            else:
                if max_bet:
                    self.session.bet_max()
                else:
                    self.session.deal()
                self.selected_card = self.selected_hand = 0
                kind = 'deal'
            after = self.session.snapshot()
            if self.cabinet and before['phase']!='hold':
                self._cabinet_game_over=False
            self.button_focus = None
            interval = (0.0 if self.manual_autoplay else self.AUTO_PROFILES[self.autoplay_speed]['animation']
                        if self.autoplay else self.SPEEDS[self.speed])
            if after['phase'] in ('hold', 'result') and interval > 0:
                self._animation = {'kind': kind, 'before': before, 'after': after,
                                   'started': self._clock(), 'interval': interval}
                self._last_stage = None
                self._update_visual(self._clock())
            if kind == 'deal':
                # Start cold imports/table checks during Deal, before the first
                # hint or best-hold gesture. This never mutates holds or RNG.
                self._request_hint(self._clock(), prepare=True)
        except RandomNotReady:
            self.notice = 'Shuffling is getting ready'
            self._entropy_notice = True
            self._credit_notice = False
            self._retry_max_bet = max_bet
        except ValueError as error:
            self.notice = str(error)
            self._entropy_notice = False
            self._credit_notice = 'credit' in self.notice.lower()
        return True

    def _button_action(self, index):
        phase = self.session.snapshot()['phase']
        if index == 0:
            self.menu = {'page': 'paytable', 'bet': self.pay_preview_bet}
        elif index == 1:
            if self.cabinet:
                if phase!='hold':
                    from poker_games import GAMES
                    self.menu={'page':'cabinet','index':next(i for i,g in enumerate(GAMES) if g.id==self.session.game.id),'return':True}
            else:self.menu = {'page': 'more_games', 'index': 0}
        elif index == 2:
            self.speed = (self.speed+1) % len(self.SPEEDS)
        elif index == 3 and not self.cabinet and phase != 'hold' and self.session.snapshot()['bet_per_hand'] == 1:
            self.session.cycle_num_hands()
            self.selected_hand = min(self.selected_hand, self.session.snapshot()['num_hands']-1)
        elif index == 4 and not self.cabinet and phase != 'hold':
            self.session.cycle_bet_per_hand()
        elif index == 5 and phase != 'hold':
            state = self.session.snapshot()
            if state['credits'] > 0 and state['credits'] >= state['total_bet']:
                return self._play(max_bet=True)
        elif index == 6:
            return self._play()
        return True

    def _menu_action(self, action):
        page = self.menu['page']
        if page=='cabinet':
            if action=='KEY3':
                if self.menu.get('return'):self.menu=None;self.button_focus=None
            elif action in ('LEFT','RIGHT','UP','DOWN'):
                self.menu['index']=(self.menu['index']+{'LEFT':-1,'RIGHT':1,'UP':-4,'DOWN':4}[action])%12
            elif action in ('CENTER','KEY1','KEY2'):
                from poker_games import GAMES
                self._cancel_advice();self._finish_animation()
                self._cabinet_game_over=self._cabinet_game_over or self.session.rounds>0
                self.session=self._cabinet_bank.select(GAMES[self.menu['index']].id,self.session)
                self.menu=self.button_focus=None
                self.selected_card=self.selected_hand=0
                self.pay_preview_bet=self.session.bet_per_hand
                self._badge_feature=bool(self.session.feature)
                self._badge_frame=0;self._badge_started=self._clock()
            return True
        if action == 'KEY3':
            self.menu = None
        elif page == 'paytable':
            if action in ('LEFT', 'RIGHT', 'UP', 'DOWN'):
                choices = (1, 2, 3, 4, 5, 10)
                index = choices.index(self.menu['bet'])
                index = max(0, min(len(choices)-1, index + (-1 if action in ('LEFT', 'DOWN') else 1)))
                self.menu['bet'] = self.pay_preview_bet = choices[index]
            elif action in ('CENTER', 'KEY1', 'KEY2'):
                self.menu = {'page': 'controls', 'index': 0}
        elif page == 'controls':
            if action in ('LEFT', 'RIGHT', 'UP', 'DOWN', 'CENTER', 'KEY1', 'KEY2'):
                count = 2 if self.session.snapshot()['phase'] == 'hold' else 4
                delta = -1 if action in ('LEFT', 'UP') else 1
                self.menu['index'] = max(0, min(count-1, int(self.menu.get('index', 0))+delta))
        elif page == 'inspect':
            if action in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
                self.menu['index'] = (int(self.menu['index']) + (-1 if action in ('UP', 'LEFT') else 1)) % len(self.session.snapshot()['hands'])
                self.selected_hand = self.menu['index']
        elif page == 'more_games' and action in ('CENTER', 'KEY1', 'KEY2'):
            self.session.add_credits()
            self.menu = None
        elif page == 'reset_confirm':
            if action in ('CENTER', 'KEY2'):
                self.session.reset()
                self.selected_card = self.selected_hand = 0
                self.menu = None
            elif action == 'KEY1':
                self.session.add_credits()
                self.menu = None
        elif page == 'options':
            if action in ('UP', 'DOWN'):
                self.menu['index'] = (self.menu['index'] + (-1 if action == 'UP' else 1)) % len(OPTIONS)
            elif action in ('CENTER', 'KEY1', 'KEY2'):
                index = self.menu['index']
                if index == 0: self.menu = {'page': 'paytable', 'bet': self.pay_preview_bet}
                elif index == 1 and self.session.snapshot()['phase'] != 'hold': self.session.set_feature(not self.session.snapshot()['feature'])
                elif index == 2: self.menu = {'page': 'reset_confirm', 'index': 0}
                elif index == 3: self.menu = {'page': 'controls', 'index': 0}
                elif index == 4: self.menu = None
        return True

    def _finish_animation(self):
        self._animation = None
        self._visual = None
        self._last_stage = None

    def update(self, now):
        if self._closed:
            return False
        peek_ready = (self._up_held and self._up_held_since is not None
                      and now-self._up_held_since >= self.HINT_HOLD_SECONDS)
        gesture_dirty = peek_ready != self._peek_ready
        self._peek_ready = peek_ready
        if self.autoplay and self._auto_up_edge is not None:
            # Give a third tap time to arrive before committing a speed change.
            if now < self._auto_up_due:
                return False
            gesture_dirty = self._commit_auto_up()
        dirty = self._update_visual(now) or gesture_dirty
        if not self.autoplay and self._manual_up_due is not None and now >= self._manual_up_due:
            self._commit_manual_up()
        if self._manual_hold_key is not None and self._animation is None:
            dirty = self._request_hint(now) or dirty
        if (self._up_held and not self.autoplay and self.menu is None
                and self.button_focus is None and self.notice is None
                and self._animation is None):
            dirty = self._request_hint(now) or dirty
        dirty = self._poll_advice(now) or dirty
        dirty = self._apply_manual_hold() or dirty
        dirty = self._update_draw_hint(now) or dirty
        dirty = self._update_autoplay(now) or dirty
        return dirty

    def _update_draw_hint(self, now):
        if not self.hint_visible or self._advice['mask'] != 0:
            changed = self._draw_hint_started is not None
            self._draw_hint_started = self._draw_hint_step = None
            return changed
        if self._draw_hint_started is None:
            self._draw_hint_started = now
        # Flash the real button face at one cycle/second, only during the
        # held no-cards hint. Other hints and normal pacing remain unchanged.
        elapsed = max(0, now-self._draw_hint_started)
        step = int((elapsed+1e-8)/(self.HINT_DRAW_FLASH_SECONDS/2))
        changed = step != self._draw_hint_step
        self._draw_hint_step = step
        return changed

    def _update_visual(self, now):
        feature = bool(self.session.snapshot()['feature'])
        feature_changed = feature != self._badge_feature
        if feature_changed:
            self._badge_started = now
            self._badge_feature = feature
        sequence = self.renderer.manifest['sequences']['active' if feature else 'inactive']
        frame = int(max(0.0, now-self._badge_started)/(sequence['duration_ms']/1000.0)+1e-8) % len(sequence['frames'])
        badge_dirty = feature_changed or frame != self._badge_frame
        self._badge_frame = frame
        badge_dirty = badge_dirty and self.menu is None
        if self._animation is None:
            return badge_dirty
        animation = self._animation
        elapsed = max(0.0, now-animation['started'])
        interval = animation['interval']
        after = animation['after']
        card_stage = min(5, int(elapsed/interval)+1)
        rollup = min(1.0, max(0.0, (elapsed-5*interval)/(3*interval)))
        is_result = after['phase'] == 'result'
        total_duration = 5*interval + (3*interval if is_result else 0)
        if elapsed >= total_duration:
            self._finish_animation()
            return True
        stage_key = (card_stage, int(rollup*12))
        if stage_key == self._last_stage:
            return badge_dirty
        self._last_stage = stage_key
        visual = dict(after)
        if animation['kind'] == 'deal' and not is_result:
            visual['_deal_reveal'] = card_stage
        else:
            # A dealt royal settles automatically, but still reveals and rolls up.
            if animation['kind'] == 'deal' and card_stage < 5:
                visual['held'] = [False]*5
            visual['_reveal'] = card_stage
            total = int(after.get('total_win', 0))
            count = int(total*rollup) if card_stage == 5 else 0
            visual['total_win'] = count
            visual['credits'] = int(after['credits'])-total+count
        self._visual = visual
        return True

    def render(self):
        snapshot = dict(self._visual if self._visual is not None else self.session.snapshot())
        if self.cabinet:snapshot['_cabinet_game_over']=self._cabinet_game_over
        snapshot['_button_focus'] = self.button_focus
        snapshot['_speed'] = self.autoplay_display_speed if self.autoplay else self.speed
        snapshot['_badge_frame'] = self._badge_frame
        image = self.renderer.render(snapshot, self.selected_card, self.selected_hand, self.menu)
        self._draw_advice(image)
        if self.notice:
            d = ImageDraw.Draw(image)
            d.rounded_rectangle((8, 76, 312, 154), radius=4, fill=(0, 0, 0), outline=GOLD, width=2)
            self.renderer.center(d, 160, 88, self.notice[:48], 10, GOLD, True)
            self.renderer.center(d, 160, 107, 'DOWN: ADD 10,000' if self._credit_notice else 'DOWN: RETRY', 11, WHITE, True)
            detail = ('Existing multipliers are kept.' if self._credit_notice else
                      'Cards and credits are unchanged.' if self._entropy_notice else
                      'K3: GAME CONTROLS')
            self.renderer.center(d, 160, 127, detail, 10, MUTED)
        if self.autoplay:
            # Native LCD pixels right of the speaker, clear of credit and controls.
            d = ImageDraw.Draw(image)
            self.renderer.text(d, (248, 207), 'A', 11, (0, 0, 0), True)
            self.renderer.text(d, (247, 206), 'A', 11, GOLD, True)
            if self.manual_autoplay:
                self.renderer.manual_auto_mark(image)
            chevrons = (256,) if self.autoplay_speed == 1 else ((256, 259) if self.autoplay_speed == 2 else ())
            for x in chevrons:
                self.renderer.speed_triangle(image, x)
        return image

    def _draw_advice(self, image):
        if not self.hint_visible:
            return
        state = self.session.snapshot()
        draw = ImageDraw.Draw(image)
        if self._advice['mask'] == 0:
            if self._draw_hint_step is None or self._draw_hint_step % 2 == 0:
                self.renderer.red_draw_button(image)
            return
        for index in range(5):
            if not self._advice['mask'] & (1 << index):
                continue
            base_x,base_y=self.renderer.base_box(state)
            top=base_y//2
            source_left = base_x+87*index
            left = int(math.floor(source_left/2.0))
            right = int(math.ceil((source_left+83)/2.0))-1
            center = int(round((source_left+41)/2.0))
            held_box = (center-15, 184, center+15, 202) if state['held'][index] else None
            held_pixels = image.crop(held_box) if held_box else None
            draw.rounded_rectangle((left-2, top-3, right+2, top+62), radius=3,
                                   outline=(0, 0, 0), width=4)
            draw.rounded_rectangle((left-1, top-2, right+1, top+61), radius=2,
                                   outline=(255, 32, 32), width=2)
            if held_pixels is not None:
                image.paste(held_pixels, held_box[:2])
