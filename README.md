🇧🇷 [Leia em português](LEIA-ME.md)

# Slayers 2 • Fishing

Automatic fishing macro for Slayers 2 (Roblox), with a Discord alert for every item caught.

⚠️ Use at your own risk: macros can violate Roblox's Terms of Service and get your account banned.

## Install (once)

1. Install Python 3.12 or newer from https://www.python.org/downloads/ and check **"Add python.exe to PATH"**.
2. Double-click `Instalar.bat`.

## Use

1. In Roblox: turn off **Screen Shake** and **Shift Lock**, equip the rod and set the camera the way you want to fish.
2. Open **Iniciar** (the shortcut with the fish logo, created by `Instalar.bat`). If it doesn't show up, use `Iniciar.bat`.
3. **Setup** tab:
   - **Mark point**: click on the water where the rod should cast. The camera (compass) is recorded along with it.
   - **Rod key**: the hotbar slot number for the rod.
   - **Adjust area**: only if the minigame bar isn't being detected.
4. **Relog** tab (optional, needs the **Set Spawn** gamepass):
   - turn on **Reconnect automatically if the game drops**;
   - check **I have the Set Spawn gamepass** and, if you already set it, **I already set the spawn at the
     fishing spot** (if you haven't, the macro sets it by itself after the 1st fish, or use **Set spawn now**);
   - choose **I have VIP** (returns to your own private server) or **I don't have VIP** and type the
     **exact nickname** of the server owner. The colored line at the top of the tab tells you what's still missing.
5. **Discord** tab (optional): paste the webhook link and your ID to get pinged on rare items.
6. **Advanced** tab (optional): switch **Language / Idioma** between English and Português. May ask
   you to reopen the macro.
7. Press **F1** (or whichever shortcut you choose) to start and stop.

## What the macro does on its own

- Checks whether the rod is equipped before casting and only presses the rod key when needed.
- Pauses if Roblox leaves the foreground, and resumes once everything is fine again.
- If the camera turns, it tries to turn it back by itself (dragging with the right button); it only
  pauses waiting for you if it can't. During a long pause it nudges the mouse 1 px every 4 min, so
  Roblox doesn't disconnect from inactivity.
- If something goes wrong (rod won't equip, several casts with no fish, an unexpected error), it
  notifies you on Discord, waits and tries again. If it gives up after several failures in a row, it
  **restarts by itself** after 5 min (up to 3 times per hour; change this in **Advanced**).
- If you move the mouse right at the moment of casting, it waits for the mouse to be free and casts again.
- If the game drops (**main menu** or **Disconnected**): with auto relog on (**Relog** tab), it
  reconnects, joins the private server, spawns at the set point and goes back to fishing. With it off,
  it stops and notifies you on Discord: log back in, return to the fishing spot and press F1. If the
  account logs in on another PC (error 264), it never reconnects.
- **Overlay** on top of the game with the macro's running time, the total of each fish and item, and
  the bait spent. It sits above the party; with fishing stopped you can drag it. What it shows (time,
  fish, Yen, items, bait and which rarities) is chosen in **Setup → Window**. Turn it on/off and
  "Back above the party" in **Setup → Window**. It doesn't show up in the macro's own screenshots and,
  while fishing, clicks pass right through it.
- **Parsec / OBS**: normally the macro window and the overlay disappear from any capture while fishing
  (in Parsec it looks like it minimized). Turn on **Setup → Window → Show up in Parsec / OBS** to see
  them; the macro erases itself from its own screenshots, so keep the window in the left corner (it
  warns you if it's covering the item alerts, the bar, the hotbar or the compass).
- **History** (Session tab): each rarity tag turns that rarity on/off in the list. Turning one off
  only hides it: the drops are still saved and come back when you turn it on again.
- **The session is saved** (history, counts, time and bait spent), even after closing the macro, until
  you click **Reset** on the Session tab. Each session's CSV stays in `logs/`.
- **Tracked item** (Discord tab, default "Ore"): total of just that item this session (Ore mythic;
  Refinement Ore is a different item), shown in the window and in every Discord message.
- Logs the main events to `logs/macro.log`. To investigate a problem, turn on **Advanced → Diagnostic
  mode**: a detailed log and a screenshot in `logs/evidencias/` for every problem (makes the macro
  heavier, so only turn it on when needed).
- **Watchdog**: if the macro freezes while fishing (5 min with no sign of life), it closes and reopens
  the macro by itself, goes back to fishing and notifies you on Discord (at most 3 times per hour).
  Where it got stuck goes to `logs/travamento.txt`; what the watchdog did goes to `logs/cao-de-guarda.log`.
- Keeps the PC from sleeping and the screen from turning off while fishing.
- Saves everything it caught to `logs/sessao-*.csv`.
- Uses an **item catalog** to know whether an item is already known, fix OCR reading mistakes and
  confirm the rarity:
  - `catalogo/` is the **shared** catalog that ships with the macro. It's read-only for the macro.
  - `catalogo_local/` is **yours**: items that aren't in the shared one yet go here (one image per
    item, never repeated), along with your own counts.
  - An item that's in neither catalog shows up on Discord as "First time in the catalog".
  - A name misread by OCR ("Clov.tn Fish", "Jzebra Fish", "Golden FEh") turns into the right item. On
    startup, the macro tidies up the local catalog: old misreads get merged into the right item and
    junk gets removed.
  - To send new items to the shared catalog: `python src/catalog.py publicar`.
  - Each item in `catalogo/itens.json` is a **card**: `"name"` (correct name), `"image"` (image in
    `catalogo/imagens/`) and `"rarity"` (common, rare, epic, legendary or mythic). The Discord alert
    and the window use the card: name, image and rarity come from it, not from the color read on
    screen. The color only counts for an item that doesn't have a card yet.
  - To fix an item, edit its card: change the `"rarity"`, change the image, or put the misread text
    under `"aliases"`. `publicar` never touches the rarity that's already on the card.

## Shortcuts

All of them can be changed in **Setup → Shortcuts**. The defaults are: F1 (start and stop), F2 (mark
the point) and F3 (close).

## Language

The interface has Portuguese (default) and English. Switch it in **Advanced → Language / Idioma**;
it may ask you to reopen the macro for the change to take effect.

## Privacy

`config.json` stores the webhook link, which works like a password. Don't send this file to anyone.
If you're passing the macro along to someone, pass the folder without `config.json`.

---
Made by zLv010x. Feel free to download and use it 🎣
