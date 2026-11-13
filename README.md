![Video Poker on a handheld](docs/images/handheld-videopoker.jpg)

# Video Poker

Twelve offline video poker games, best-hold hints, autoplay, a calculator and a hidden trainer. Virtual credits only.

[Download v0.6.6 IMG](https://github.com/xberenguer/videopoker/releases/download/v0.6.6/videopoker-v0.6.6-pi0-320x240.img) · [Release](https://github.com/xberenguer/videopoker/releases/tag/v0.6.6) · [Buy or build the handheld](#get-the-hardware)

[Complete user guide](docs/USER-GUIDE.md) · [All menus and settings](docs/USER-GUIDE.md#general-settings) · [Trainer and statistics](docs/USER-GUIDE.md#hidden-trainer) · [Build and validation](docs/TECHNICAL.md) · [Licenses and credits](NOTICE)

## Quick install

You'll need the handheld, a microSD card, a computer and a card reader.

1. [Download the game image (.img)](https://github.com/xberenguer/videopoker/releases/download/v0.6.6/videopoker-v0.6.6-pi0-320x240.img) and install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Insert the microSD card into your computer using a card reader, then open Imager.
3. Choose **Raspberry Pi Zero** as the device. For the operating system, choose **Use Custom** and open the downloaded `.img` file.
4. Choose your **microSD card** as storage. Skip OS customisation if asked.
5. Click **Write**, confirm erasing that card and approve the computer's permission prompt. Let writing and verification finish.
6. Eject the card, put it in the powered-off handheld's boot slot (**top slot on Play**) and connect USB power. The game opens automatically.

## Get the hardware

- **Buy assembled:** [SeedSigner Play](https://bitkitbtc.com/product/seedsigner-play/) or [SeedSigner Plus](https://bitkitbtc.com/product/seedsigner-plus/) from BitKit. Choose a **Pi Zero 1.3 / 320 × 240** configuration for this image.
- **Build the handheld:** use a Pi Zero 1.3, a [Plus display HAT](https://github.com/3rdIteration/seedsigner-hardware/tree/main/display_hats/plus_hat), a suitable case and a microSD card. The linked project includes board design, fabrication and display details. The regular 240 × 240 HAT needs a different image.
- **Build the software:** [source and image-build instructions](docs/TECHNICAL.md#build-from-source).

[Optional download verification](docs/USER-GUIDE.md#verify-the-download) · [Official Imager guide](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager)

## Play

| Input | Action |
| --- | --- |
| LEFT / RIGHT | Select cards or bottom machine controls |
| Either middle button | Hold/unhold, select, or next deal after results |
| DOWN | Deal / Draw |
| Hold UP | Red best-hold peek after 0.30 seconds; release hides it |
| Double UP | Apply best holds manually; change mode during autoplay |
| Triple UP | Toggle autoplay on/off |
| Cabinet BOTTOM | General Settings |
| Hold right-column TOP + BOTTOM for two seconds | Toggle the live trainer sidebar on/off immediately, before release |

When no cards should be held, held-UP flashes the actual Draw button red. Fast taps deliberately do not show the red hint. Both middle buttons retain their card-hold/next-hand behavior.

Autoplay starts in **AM**: DOWN deals, then another DOWN applies the best hold and draws immediately. Double UP cycles **AM → Medium → Fast**. The small footer indicator uses `A M`, one filled triangle or two filled triangles. UP does not cancel autoplay except an explicit triple tap; AM also keeps autoplay active when DOWN is pressed. See the [complete control guide](docs/USER-GUIDE.md#physical-controls).

| Cabinet | Ten-hand play |
| --- | --- |
| ![Twelve-game cabinet](docs/screenshots/live-regular-menu.png) | ![Ten-hand Double Double Bonus](docs/screenshots/live-regular-game.png) |
| ![Three-hand play](docs/screenshots/live-triple-ddb.png) | ![Five-hand Deuces Wild](docs/screenshots/live-five-deuces.png) |

## Settings and Vegas paytables

General Settings includes **brightness, manual animation speed, paytable presets, persistent memory and virtual-credit reset**. Each setting has a short explanation. Three- and ten-hand Double Double Bonus offer **9/6, 9/5, 8/5 and 7/5**, with matching payout and offline strategy data. Other games retain their original cabinet tables.

The ten-hand **7/5 DDB** preset matches the [supplied South Point paytable photo](docs/images/south-point-ddb-75.jpg), including its multiplier schedule. Casino names do not establish one universal configuration. Review the actual awards and multipliers; [preset details](docs/USER-GUIDE.md#paytable-presets-and-vegas-configurations) explain what is verified.

| General settings | Optional memory |
| --- | --- |
| ![General Settings](docs/screenshots/settings-general.png) | ![Persistent memory with explanation](docs/screenshots/settings-memory-on.png) |

## Memory

**OFF is the factory default.** Training and device settings stay in RAM and disappear after power-off. ON saves device preferences, per-preset training settings, error history and statistics. Turning OFF clears the saved copies while keeping the current RAM session. A separate confirmed **Clear training data** action resets training records while preserving device settings and the memory preference.

Cards, held flags, live credits, game multipliers, RNG state and active autoplay always reset after power-off. Boot always selects the first cabinet tile, **Triple Play Bonus Poker**. The program checks the saved preference at startup; OFF does not mean that boot performs no SD reads. [Storage behavior and save status](docs/USER-GUIDE.md#persistent-memory).

## Trainer and calculator

Ordinary gameplay has no training labels or sidebar. The hidden trainer offers TEST/COACH modes, inline error feedback, live Advice/EV/Stats panels, all 32 hold alternatives, payout probabilities, error review/replay, practice drills and separate autoplay statistics. Assisted decisions stay separate from personal accuracy.

The calculator starts automatically when the fifth card is confirmed, then refreshes after complete-hand input changes. It displays **EV**, **NOW** and **NEXT**, with **COMPARE EV** for the full ranked list. It uses the selected game's exact paytable, deck and current multiplier board.

| Live coach | Inline error feedback |
| --- | --- |
| ![Live coach panel](docs/screenshots/live-coach.png) | ![Incorrect-hold feedback](docs/screenshots/live-error.png) |
| ![Live EV panel](docs/screenshots/live-ev.png) | ![Personal session statistics](docs/screenshots/live-stats.png) |
| ![Calculator EV](docs/screenshots/calculator-inline-ev.png) | ![Autoplay statistics](docs/screenshots/autoplay-session-stats.png) |

EV retained measures decision quality; it is not casino RTP or a profit guarantee. Continued-play values use a numerical all-1× reference. Identical vendor XEV formatting is not claimed. [EV definitions and limits](docs/USER-GUIDE.md#statistics-and-ev).

## Build and verification

See [technical notes](docs/TECHNICAL.md) for the pinned base OS, source assembly, tests, numerical policy generation and release evidence. Host and stock ARM emulation checks cover all twelve games and the additional paytable policies. Physical cold boot, LCD/PWM behavior, GPIO and Pi timing still need hardware testing.

This independent community project is not an official casino or game-vendor release. Original code is GPL-2.0-or-later; third-party components, artwork, marks and font-derived bitmaps retain their own rights. See [LICENSE](LICENSE), [NOTICE](NOTICE) and `payload/opt/dino/THIRD-PARTY-ASSETS.txt`.
