"""Built-in commands: common phrases in English, Hindi and Hinglish that need no AI, no internet and no key.

The whole sentence must match. "Volume 30 karke YouTube kholo" doesn't, so it goes to the AI instead of
half-running. Each match becomes an ordinary tool call, so the same safety rules apply.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass
class Intent:
    tool: str
    input: dict
    reply: str     # what to tell the user; empty = show what the tool found


_DO = r"(?: ?(?:karo|kar do|kardo|kar dijiye|kijiye|please|plz|करो|कर दो|कीजिए|कर दीजिए|please))*"
_VOL = r"(?:volume|sound|awaaz|awaz|aawaz|avaaz|आवाज़|आवाज|वॉल्यूम|वॉल्युम)"
_BRI = r"(?:brightness|screen brightness|roshni|ब्राइटनेस|रोशनी)"
_UP = r"(?:up|increase|louder|higher|badhao|badha|badhaao|badha do|tez|zyada|बढ़ाओ|बढ़ा|बढ़ा दो|तेज|ज्यादा|ज़्यादा)"
_DOWN = r"(?:down|decrease|lower|reduce|kam|ghatao|dheere|dheemi|कम|घटाओ|धीमी|धीरे)"
_PCT = r"(?: ?(?:percent|percentage|%|pe|par|पर|प्रतिशत|ko|को|to))*"
_OF = r"(?: (?:ko|को|to))?"
_LAPTOP = r"(?:(?:laptop|computer|pc|system|लैपटॉप|कंप्यूटर|सिस्टम)(?: ko| को)? )?"
_OPEN = r"(?:kholo|khol do|open karo|open kar do|open|chalao|chala do|start karo|खोलो|खोल दो|चलाओ)"

SITES = {
    "youtube": "https://www.youtube.com", "यूट्यूब": "https://www.youtube.com",
    "google": "https://www.google.com", "गूगल": "https://www.google.com",
    "gmail": "https://mail.google.com", "जीमेल": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com", "whatsapp web": "https://web.whatsapp.com", "व्हाट्सएप": "https://web.whatsapp.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "maps": "https://www.google.com/maps",
    "google maps": "https://www.google.com/maps", "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com", "wikipedia": "https://www.wikipedia.org",
    "linkedin": "https://www.linkedin.com", "twitter": "https://x.com", "github": "https://github.com",
    "zoho mail": "https://mail.zoho.com",
}
APPS = {
    "notepad": "notepad", "नोटपैड": "notepad", "calculator": "calc", "calc": "calc", "कैलकुलेटर": "calc",
    "paint": "mspaint", "chrome": "chrome", "क्रोम": "chrome", "edge": "msedge", "word": "winword",
    "excel": "excel", "powerpoint": "powerpnt", "file explorer": "explorer", "explorer": "explorer",
    "settings": "ms-settings:", "vlc": "vlc", "spotify": "spotify:", "google chrome": "chrome", "task manager": "taskmgr",
    "control panel": "control",
}
_NAMES = "|".join(sorted((re.escape(k) for k in {**SITES, **APPS}), key=len, reverse=True))

_RULES: list[tuple[str, object]] = [
    # volume
    (rf"(?:set )?{_VOL}{_OF} (\d{{1,3}}){_PCT}{_DO}", lambda m: Intent("set_volume", {"percent": min(100, int(m[1]))}, f"Volume {min(100, int(m[1]))}%")),
    (rf"{_VOL}(?: thodi| थोड़ी)? {_UP}{_DO}", lambda m: Intent("change_volume", {"direction": "up"}, "Volume up")),
    (rf"{_VOL}(?: thodi| थोड़ी)? {_DOWN}{_DO}", lambda m: Intent("change_volume", {"direction": "down"}, "Volume down")),
    (rf"{_LAPTOP}(?:mute|म्यूट){_DO}|{_VOL} (?:band|बंद){_DO}", lambda m: Intent("mute", {"muted": True}, "Muted")),
    (rf"{_LAPTOP}(?:unmute|अनम्यूट){_DO}|{_VOL} (?:chalu|on|चालू){_DO}", lambda m: Intent("mute", {"muted": False}, "Unmuted")),
    # brightness
    (rf"(?:set )?{_BRI}{_OF} (\d{{1,3}}){_PCT}{_DO}", lambda m: Intent("set_brightness", {"percent": min(100, int(m[1]))}, f"Brightness {min(100, int(m[1]))}%")),
    (rf"{_BRI}(?: thodi| थोड़ी)? {_UP}{_DO}", lambda m: Intent("change_brightness", {"direction": "up"}, "Brightness up")),
    (rf"{_BRI}(?: thodi| थोड़ी)? {_DOWN}{_DO}", lambda m: Intent("change_brightness", {"direction": "down"}, "Brightness down")),
    # media
    (rf"(?:next|next song|next track|skip|agla|agla gaana|agla gana|agla song|next gaana|अगला|अगला गाना){_DO}", lambda m: Intent("media", {"action": "next"}, "Next track")),
    (rf"(?:previous|previous song|prev|pichla|pichla gaana|pichla gana|पिछला|पिछला गाना){_DO}", lambda m: Intent("media", {"action": "previous"}, "Previous track")),
    (rf"(?:pause|play|resume|ruko|rok do|gaana roko|gana roko|gaana chalao|gana chalao|gaana band|रोको|रोक दो|गाना रोको|गाना चलाओ|गाना बंद){_DO}", lambda m: Intent("media", {"action": "play_pause"}, "Play / pause")),
    # power
    (rf"(?:lock|lock (?:the )?laptop|{_LAPTOP}(?:lock|लॉक)){_DO}", lambda m: Intent("power", {"action": "lock"}, "Locked")),
    (rf"(?:screen off|display off|turn off (?:the )?(?:screen|display)|screen band|display band|स्क्रीन बंद){_DO}", lambda m: Intent("power", {"action": "display_off"}, "Display off")),
    (rf"(?:sleep|{_LAPTOP}(?:sula do|sleep|सुला दो|स्लीप)){_DO}", lambda m: Intent("power", {"action": "sleep"}, "Going to sleep")),
    (rf"(?:restart|reboot|{_LAPTOP}(?:restart|रीस्टार्ट)){_DO}", lambda m: Intent("power", {"action": "restart"}, "Restarting")),
    # "band karo" alone is too vague to mean the whole laptop: it must name it
    (rf"(?:shutdown|shut down|power off|{_LAPTOP}(?:shutdown|shut down)|(?:laptop|computer|pc|system|लैपटॉप|कंप्यूटर|सिस्टम)(?: ko| को)? (?:band|बंद)){_DO}", lambda m: Intent("power", {"action": "shutdown"}, "Shutting down")),
    # shortcuts
    (rf"(?:show desktop|desktop dikhao|desktop|डेस्कटॉप दिखाओ){_DO}", lambda m: Intent("press_keys", {"keys": "win+d"}, "Desktop")),
    (rf"(?:screenshot|screenshot lo|take (?:a )?screenshot|स्क्रीनशॉट लो){_DO}", lambda m: Intent("press_keys", {"keys": "win+shift+s"}, "Screenshot tool opened")),
    # open
    (rf"(?:(?:open|start|launch) )?({_NAMES})(?: {_OPEN})?{_DO}", lambda m: _open(m[1])),
]
_COMPILED = [(re.compile(p), f) for p, f in _RULES]


# Services with a desktop app too: opened as the installed app when there is one (the tool falls back to the site)
_APP_FIRST = {"chatgpt": "ChatGPT", "claude": "Claude", "whatsapp": "WhatsApp", "whatsapp web": "WhatsApp",
              "व्हाट्सएप": "WhatsApp", "netflix": "Netflix", "instagram": "Instagram", "facebook": "Facebook",
              "spotify": "Spotify", "linkedin": "LinkedIn"}


def _open(name: str) -> Intent:
    if name in _APP_FIRST:
        return Intent("open_app", {"name": _APP_FIRST[name]}, f"Opened {_APP_FIRST[name]}")
    if name in SITES:
        return Intent("open_url", {"url": SITES[name]}, f"Opened {name}")
    return Intent("open_app", {"name": APPS[name]}, f"Opened {name}")


def _clean(text: str) -> str:
    t = text.lower().replace("​", "").strip()
    t = re.sub(r"[.,!?;:।\"']+", " ", t)
    t = re.sub(r"^(?:hey |hi |ok |okay |please |plz )+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"(\d) ?%", r"\1 percent", t)


def match(text: str) -> Intent | None:
    t = _clean(text)
    if not t or len(t) > 80:
        return None
    for rx, make in _COMPILED:
        m = rx.fullmatch(t)
        if m:
            return make(m)
    return None


# ---------------- everyday sentences, without AI ----------------
# "can you turn the sound down a bit", "thoda awaaz kam kar do yaar", "volume 30 aur youtube kholo".
# Not real understanding: it looks for the words that matter, and gives up rather than guess. A sentence
# touching two different things, a "don't", or a "how do I" goes back to the caller unanswered.

_NEGATIVE = {"not", "dont", "never", "mat", "nahi", "nahin", "मत", "नहीं"}
_HOW = {"how", "why", "when", "kaise", "kyun", "kyu", "kab", "कैसे", "क्यों", "कब"}
_ASK = {"kitna", "kitni", "what", "whats", "check", "batao", "bata", "tell", "show", "status", "कितना", "कितनी", "बताओ", "how"}
_FILLER = sorted([
    "can you", "could you", "would you", "will you", "i want to", "i want", "i need to", "i need", "i would like to",
    "id like to", "little bit", "for me", "mere liye", "please", "plz", "pls", "kindly", "the", "my", "a", "an", "just",
    "now", "abhi", "yaar", "yar", "bhai", "zara", "jara", "thoda", "thodi", "thora", "thori", "little", "bit", "some",
    "mujhe", "meri", "mera", "mere", "kripya", "hey", "hi", "ok", "okay", "assistant", "fasway", "na", "app", "application",
    "wala", "waala", "si", "sa", "ko", "koi", "jaldi", "bas", "sir", "software", "program", "कृपया", "थोड़ा", "थोड़ी", "ज़रा", "जरा", "मेरा", "मेरी", "मुझे", "अभी", "भाई", "यार",
], key=len, reverse=True)
_LEADING = re.compile(r"^(?:(?:hey|hi|ok|okay|please|plz|pls|kindly|can you|could you|would you|will you|"
                      r"i want to|i need to|i would like to|i wanna|zara|jara|yaar|yar|bhai|अरे|are|arre|कृपया)\s+)+", re.I)
_TRAILING = re.compile(r"(?:\s+(?:please|plz|pls|for me|mere liye|yaar|yar|bhai|jaldi|na|karo|kar do|kardo|kar de|karde|kar dena|"
                       r"kijiye|kar dijiye|करो|कर दो|कर दे))+$", re.I)
_SPLIT = re.compile(r"\s*[,;]\s*|\s+(?:and then|after that|and|then|aur|phir|fir|karke|kar ke|और|फिर|करके|कर के)\s+", re.I)

_VOL_W = {"volume", "sound", "awaaz", "awaz", "aawaz", "avaaz", "आवाज़", "आवाज", "वॉल्यूम", "वॉल्युम"}
_BRI_W = {"brightness", "roshni", "ब्राइटनेस", "रोशनी", "brighter", "dim", "darker"}
_MUSIC_W = {"song", "songs", "gaana", "gana", "ganna", "gaane", "gane", "geet", "music", "track", "video", "videos", "गाना",
            "गाने", "गीत", "संगीत", "वीडियो"}
_PC_W = {"laptop", "computer", "pc", "system", "लैपटॉप", "कंप्यूटर", "सिस्टम"}
_SCREEN_W = {"screen", "display", "स्क्रीन"}
_OFF_W = {"off", "band", "बंद"}
_UP_W = {"up", "increase", "raise", "more", "louder", "higher", "high", "brighter", "badhao", "badha", "badhana", "tez", "tej",
         "zyada", "jyada", "बढ़ाओ", "बढ़ा", "तेज", "ज्यादा", "ज़्यादा"}
_DOWN_W = {"down", "decrease", "lower", "low", "reduce", "less", "quieter", "softer", "dim", "darker", "kam", "ghatao", "ghata",
           "dheere", "dheemi", "dheema", "कम", "घटाओ", "घटा", "धीमी", "धीरे"}
_NEXT_W = {"next", "skip", "agla", "agle", "dusra", "change", "badlo", "badal", "hatao", "hata", "अगला", "अगले", "दूसरा", "बदलो", "हटाओ"}
_WINDOW_NAMES = {"word": "word", "calculator": "calculator", "calc": "calculator"}
_PREV_W = {"previous", "prev", "pichla", "pichle", "pichhla", "back", "पिछला", "पिछले"}


def _hi(stem: str) -> set[str]:
    """Every way Hindi says the same request: khol -> kholo, khol do, khol de, khol dena, kholna, kholiye..."""
    return {stem, stem + "o", stem + "na", stem + "iye", f"{stem} do", f"{stem} de", f"{stem} dena", f"{stem} dijiye", f"{stem} dijie"}


def _hi_deva(stem: str, polite: str) -> set[str]:
    return {stem, polite, f"{stem} दो", f"{stem} दे", f"{stem} देना", f"{stem} दीजिए"}


def _do(word: str) -> set[str]:
    return {word, *(f"{word} {k}" for k in ("karo", "kar", "kar do", "kar de", "kardo", "karde", "kar dena", "kijiye", "करो", "कर दो", "कर दे"))}


_PLAY_ONLY_F = _hi("laga") | _hi("baja") | _hi("suna") | _hi_deva("लगा", "लगाओ") | _hi_deva("बजा", "बजाओ") | _hi_deva("सुना", "सुनाओ")
_PLAY_F = _PLAY_ONLY_F | _hi("chala") | _hi_deva("चला", "चलाओ") | _do("play") | {"put on"}
_FIND_F = _hi("dhund") | _hi("dhundh") | _hi("dhoond") | _hi("khoj") | _do("search") | _do("सर्च") | {"find", "look up", "look for"} \
    | _hi_deva("ढूंढ", "ढूंढो") | _hi_deva("खोज", "खोजो")
_SHOW_F = _hi("dikha") | _hi_deva("दिखा", "दिखाओ") | {"show"}
_OPEN_F = _hi("khol") | _do("open") | _hi_deva("खोल", "खोलो") | {"start", "launch", "go to", "jao", "जाओ"}
_WRITE_F = _hi("likh") | _hi_deva("लिख", "लिखो") | _do("type")
_OPEN_W = _OPEN_F | _hi("chala") | _hi_deva("चला", "चलाओ")
_PAUSE_W = _PLAY_F | {"pause", "stop", "ruko", "roko", "rok", "rok do", "band", "बंद", "रोको", "resume"}
_SEARCH_NAMES = {"google": "google", "गूगल": "google", "youtube": "youtube", "यूट्यूब": "youtube", "maps": "maps",
                 "wikipedia": "wikipedia", "amazon": "amazon", "flipkart": "flipkart"}
_ON = r"(?:on|in|pe|par|per|me|mein|पर|में)"
# how speech recognition writes names, and everyday slips
_SPEECH = [(re.compile(p, re.I), r) for p, r in ((r"\byou ?tube\b", "youtube"), (r"\bwhats? ?app\b", "whatsapp"), (r"\bg ?mail\b", "gmail"),
                                                 (r"\bnote ?pad\b", "notepad"), (r"\bcalculater\b", "calculator"),
                                                 (r"\bgoogle ?chrome\b", "google chrome"))]
_ALIASES = {"setting": "settings", "file manager": "file explorer", "my computer": "file explorer", "this pc": "file explorer",
            "calculator app": "calculator", "सेटिंग": "settings", "सेटिंग्स": "settings", "ms word": "word", "ms excel": "excel",
            "cloud": "claude", "cloud ai": "claude", "chat gpt": "chatgpt", "raho mail": "zoho mail", "raho mel": "zoho mail",
            "zoho mel": "zoho mail"}
_KEYS = {"save": "ctrl+s", "save this": "ctrl+s", "undo": "ctrl+z", "copy": "ctrl+c", "paste": "ctrl+v", "select all": "ctrl+a",
         "press enter": "enter", "refresh": "f5", "new tab": "ctrl+t", "close tab": "ctrl+w", "close window": "alt+f4",
         "close this window": "alt+f4", "window band": "alt+f4", "window band karo": "alt+f4", "minimize all": "win+d",
         "minimise all": "win+d", "minimize everything": "win+d", "minimise everything": "win+d", "go to desktop": "win+d",
         "take screenshot": "win+shift+s", "copy this": "ctrl+c", "copy this text": "ctrl+c", "paste this": "ctrl+v"}
# asking for something to be composed, which only the AI can do: typing the words "a poem" would be wrong
_COMPOSE = {"a", "an", "some", "my", "ek", "email", "mail", "letter", "essay", "poem", "story", "summary", "code",
            "application", "kavita", "kahani", "patra"}


def _has(t: str, words) -> bool:
    return any(f" {w} " in f" {t} " for w in words)


def _strip_filler(t: str) -> str:
    t = f" {t} "
    for f in _FILLER:
        t = t.replace(f" {f} ", " ").replace(f" {f} ", " ")
    return re.sub(r"\s+", " ", t).strip()


def _alt(words) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


def _search(site: str, query: str, named: bool = False) -> Intent | None:
    """`named`: the user said which site, so even "songs" is a search there."""
    q = query.strip(" \"'.,!?")
    low = q.lower()
    if not q or _has(low, _VOL_W | _BRI_W | {"file", "files", "folder", "document", "फाइल"}):
        return None
    if _SPLIT.search(q) and _has(low, _OPEN_F | _PLAY_F | _FIND_F):
        return None   # "notepad kholo aur youtube pe arijit chalao" is two instructions: split it first
    # "play music", "play the next song": that's the player, not a search
    if not named and set(_strip_filler(low).split()) <= _MUSIC_W | _NEXT_W | _PREV_W | {"koi", "ek", "achha", "accha", "wala"}:
        return None
    return Intent("web_search", {"site": _SEARCH_NAMES[site], "query": q}, f"Searching {_SEARCH_NAMES[site]} for {q}")


def _play(site: str, query: str, named: bool = False) -> Intent | None:
    """Play the top YouTube result (same checks as a search: "play the next song" is the player, not YouTube)."""
    hit = _search("youtube", query, named)
    if not hit:
        return None
    q = hit.input["query"]
    return Intent("play_youtube", {"query": q}, "")   # the tool's own words name the video it found


def _on_site(s: str) -> list[Intent] | None:
    """A sentence naming a site, in any word order: "youtube arijit ke gane chala de", "play songs on youtube",
    "arijit singh youtube pe lagao", "youtube pe arijit". What's left after the site and the verb is the search."""
    low = f" {s.lower()} ".replace(" google maps ", " maps ")
    low = re.sub(r" (?:on|in|pe|me|mein) (?:edge|chrome|browser|firefox) ", " ", low)   # sites open in the default browser
    if " google chrome " in low:
        return None
    site = next((n for n in _SEARCH_NAMES if f" {n} " in low), None)
    if not site:
        return None
    said_on = re.search(rf" {site} {_ON} ", low)
    rest = re.sub(rf" {site}(?: {_ON})? ", " ", low, count=1).strip()

    def after_verb(forms) -> str | None:
        alt = _alt(forms)
        m = re.fullmatch(rf"(?:{alt})(?: (.*))?", rest) or re.fullmatch(rf"(.*?) ?(?:{alt})", rest)
        return None if m is None else (m[1] or "")

    def trim(q: str) -> str:
        return re.sub(rf"^(?:{_ON} )+|(?: {_ON})+$", "", q).strip()

    # "chala do" / "play" on YouTube = play it; "search" / "dikhao" = show the results
    playing = _SEARCH_NAMES[site] == "youtube" and after_verb(_PLAY_F) is not None
    query = after_verb(_PLAY_F | _FIND_F | _SHOW_F)
    if query is not None:
        query = trim(query)
        if not query:
            return [_open(site)]
        hit = (_play if playing else _search)(site, query, named=True)
        return [hit] if hit else None
    if not rest or after_verb(_OPEN_F) == "":
        return [_open(site)]
    # no verb at all: "youtube pe arijit", "google weather in delhi"
    if said_on or (site in ("google", "गूगल") and (low.strip().startswith(site) or low.strip().endswith(site))):
        hit = _search(site, trim(rest), named=True)
        return [hit] if hit else None
    return None


def _explicit(raw: str) -> list[Intent] | None:
    """Sentences where part of the text is the content (what to search, what to type): the words are kept as said."""
    s = _TRAILING.sub("", _LEADING.sub("", raw.strip().rstrip(".!?। "))).strip()
    if not s:
        return None
    named = _on_site(s)
    if named:
        return named
    pick = lambda p: re.fullmatch(p, s, re.I)   # noqa: E731
    m = pick(rf"(.+?)(?: (?:ke|ka|ki|के|का|की))? ({_alt(_MUSIC_W)}) (?:{_alt(_PLAY_F)})")
    if m:
        hit = _play("youtube", f"{m[1]} {m[2]}")
        return [hit] if hit else None
    m = pick(rf"(.+?) (?:{_alt(_PLAY_ONLY_F | _do('play'))})")   # "arijit laga do": "laga" and "baja" are only ever for music
    if m and not _has(m[1].lower(), {"alarm", "timer", "reminder", "password"}):
        hit = _play("youtube", m[1])
        return [hit] if hit else None
    m = pick(rf"(.+?) (?:{_alt(_hi('chala') | _hi_deva('चला', 'चलाओ'))})")
    if m and (len(m[1].split()) >= 3 or _has(m[1].lower(), {"ka", "ke", "ki", "का", "के", "की"})):
        # "tum hi ho chalao": too long for an app name, and "chalao" with a title means play it
        hit = _play("youtube", m[1])
        return [hit] if hit else None
    m = pick(r"(?:play|put on) (.+)")
    if m:
        hit = _play("youtube", m[1])
        return [hit] if hit else None
    m = pick(r"(?:search|find|look up|look for)(?: for)? (.+)") or pick(rf"(.+?) (?:{_alt(_FIND_F)})")
    if m:
        hit = _search("google", m[1])
        return [hit] if hit else None

    # typing: "write hello in notepad", "notepad me hello likho", "type hello"
    target = None
    m = pick(rf"(?:type|write) (.+?) (?:in|into) ({_NAMES})") or pick(r"(?:type|write) (.+?)()")
    if m:
        text, target = m[1], m[2].lower()
    else:
        m = pick(rf"({_NAMES}) (?:me|mein|में) (.+?) (?:{_alt(_WRITE_F)})")
        if m:
            target, text = m[1].lower(), m[2]
        else:
            m = pick(rf"(.+?) (?:{_alt(_WRITE_F)})")
            if not m:
                return None
            text = m[1]
    if set(text.lower().split()) & _COMPOSE:
        return None
    text = text.strip(" \"'")
    steps = [_open(target)] if target else []
    return [*steps, Intent("type_text", {"text": text}, "Typed it")]


def _status(t: str) -> Intent | None:
    if _has(t, {"time", "date", "din", "baje", "samay", "tareekh", "tarikh", "टाइम", "समय", "बजे", "तारीख"}) and (
            _has(t, _ASK | {"kya", "kitne", "which", "today", "aaj", "क्या", "कितने", "आज"}) or t in ("time", "date")):
        return Intent("get_time", {}, "")   # "time kya hai", "kitne baje hain", "what's the date today"
    if _has(t, {"battery", "बैटरी"}) and not _has(t, _OPEN_W | {"saver", "settings"}):
        return Intent("get_system_status", {}, "")   # "battery percentage", "battery?": only ever a question
    if not _has(t, _ASK):
        return None
    if _has(t, {"battery", "बैटरी", "charge", "cpu", "ram", "memory"}) or _has(t, _VOL_W) or _has(t, _BRI_W):
        return Intent("get_system_status", {}, "")
    if _has(t, {"playing", "chal raha", "chal rahi", "baj raha", "which song", "kaunsa gaana", "kaun sa gaana", "चल रहा"}):
        return Intent("get_now_playing", {}, "")
    if _has(t, {"windows", "open apps", "apps open"}):
        return Intent("get_windows", {}, "")
    return None


def _clause(raw: str, last: str | None = None) -> Intent | None:
    """One instruction, by the words that matter. None if it isn't clear.
    `last`: "volume" or "brightness" if that was just changed, so "aur kam karo" or "30 percent" continue it."""
    exact = match(raw)
    if exact:
        return exact
    plain = _TRAILING.sub("", _LEADING.sub("", raw.strip().rstrip("!?। "))).lower()
    m = (re.fullmatch(r"(?:open|launch|go to) ([\w-]+(?:\.[\w-]+)+)", plain)
         or re.fullmatch(r"([\w-]+(?:\.[\w-]+)+) (?:kholo|khol do|खोलो|खोल दो)", plain))
    if m:   # always as a web address, so a name like "setup.bat" can never run a local file
        return Intent("open_url", {"url": f"https://{m[1]}"}, f"Opened {m[1]}")
    t = _strip_filler(_clean(raw.replace("'", "")))
    if not t or len(t.split()) > 12:
        return None
    t = f" {t} "
    for said, meant in _ALIASES.items():
        t = t.replace(f" {said} ", f" {meant} ")
    t = t.strip()
    asked = _status(t)
    if asked:
        return asked
    if _has(t, _HOW):
        return None
    keys = _KEYS.get(t) or _KEYS.get(_TRAILING.sub("", t)) or _KEYS.get(re.sub(rf" (?:{_alt(_OPEN_F)})$", "", t))
    if keys:
        return Intent("press_keys", {"keys": keys}, "Done")
    if t in ("ruk jao", "ruk ja", "रुक जाओ"):
        return Intent("media", {"action": "play_pause"}, "Play / pause")
    if _has(t, {"weather", "mausam", "मौसम"}):
        q = _LEADING.sub("", raw.strip().rstrip("?.! "))
        return Intent("web_search", {"site": "google", "query": q}, "Searching Google for the weather")
    number = re.search(r"\d{1,3}", t)
    pct = min(100, int(number[0])) if number else None

    vol, bri, music = _has(t, _VOL_W | {"louder", "quieter", "too loud"}), _has(t, _BRI_W), _has(t, _MUSIC_W)
    screen = _has(t, _SCREEN_W)
    if screen and not bri and not _has(t, _OFF_W) and (pct is not None or _has(t, _UP_W) or _has(t, _DOWN_W)):
        bri = True   # "make the screen brighter", "screen 60"
    plain_web = re.fullmatch(rf"(?:open |go to )?(.+?) (?:on|in|pe|me|mein) (?:edge|chrome|browser|firefox|web)"
                             rf"(?: (?:{_alt(_OPEN_W)}))?", t) \
        or re.fullmatch(rf"(?:open |go to )?(.+?) (?:website|site|web ?site|वेबसाइट)(?: (?:{_alt(_OPEN_W)}))?", t)
    if plain_web and plain_web[1] not in _SEARCH_NAMES:
        name = plain_web[1]
        if name in SITES:
            return _open(name)
        # a site we don't have the address of: search for it, rather than guess an address
        return Intent("web_search", {"site": "google", "query": name}, f"Searching for {name}")
    if last and not (vol or bri or music) and len(t.split()) <= 4 and (
            pct is not None or _has(t, _UP_W | _DOWN_W | {"aur", "more", "again", "aur thoda", "और"})):
        vol, bri = last == "volume", last == "brightness"   # a follow-up: "3 percent", "aur kam karo"
    pc = _has(t, _PC_W)
    power = (_has(t, {"lock", "लॉक", "restart", "reboot", "रीस्टार्ट", "shutdown", "shut down", "shut it down", "sign out", "log out",
                      "power off", "sleep", "sula", "स्लीप", "सुला"})
             or (pc and _has(t, _OFF_W | {"turn off", "switch off"})) or (screen and _has(t, _OFF_W)))
    site = next((n for n in sorted({**SITES, **APPS}, key=len, reverse=True) if f" {n} " in f" {t} "), None)
    if sum([vol, bri, music, bool(power), bool(site)]) > 1:
        return None   # two different things and no clear split: don't pick one

    if vol:
        if pct is not None:
            return Intent("set_volume", {"percent": pct}, f"Volume {pct}%")
        if _has(t, {"too loud", "bahut tez", "tez hai", "tej hai", "bahut zyada", "zyada hai", "बहुत तेज", "तेज है", "ज्यादा है"}):
            return Intent("change_volume", {"direction": "down"}, "Volume down")   # describing the problem, not asking for more
        if _has(t, {"full", "max", "maximum", "poora", "पूरा"}):
            return Intent("set_volume", {"percent": 100}, "Volume 100%")
        if _has(t, {"unmute", "chalu", "on", "चालू", "अनम्यूट"}):
            return Intent("mute", {"muted": False}, "Unmuted")
        if _has(t, {"mute", "silent", "chup", "off", "band", "बंद", "म्यूट"}):
            return Intent("mute", {"muted": True}, "Muted")
        if _has(t, _UP_W):
            return Intent("change_volume", {"direction": "up"}, "Volume up")
        if _has(t, _DOWN_W):
            return Intent("change_volume", {"direction": "down"}, "Volume down")
        return None
    if bri:
        if pct is not None:
            return Intent("set_brightness", {"percent": pct}, f"Brightness {pct}%")
        if _has(t, {"full", "max", "maximum", "poora", "पूरा"}):
            return Intent("set_brightness", {"percent": 100}, "Brightness 100%")
        if _has(t, _DOWN_W):
            return Intent("change_brightness", {"direction": "down"}, "Brightness down")
        if _has(t, _UP_W):
            return Intent("change_brightness", {"direction": "up"}, "Brightness up")
        return None
    if music:
        if _has(t, _PREV_W):
            return Intent("media", {"action": "previous"}, "Previous track")
        if _has(t, _NEXT_W):
            return Intent("media", {"action": "next"}, "Next track")
        if _has(t, _PAUSE_W):
            return Intent("media", {"action": "play_pause"}, "Play / pause")
        return None
    if power:
        if screen:
            return Intent("power", {"action": "display_off"}, "Display off")
        if _has(t, {"restart", "reboot", "रीस्टार्ट"}):
            return Intent("power", {"action": "restart"}, "Restarting")
        if _has(t, {"sign out", "log out"}):
            return Intent("power", {"action": "signout"}, "Signing out")
        if _has(t, {"lock", "लॉक"}):
            return Intent("power", {"action": "lock"}, "Locked")
        if _has(t, {"sleep", "sula", "स्लीप", "सुला"}):
            return Intent("power", {"action": "sleep"}, "Going to sleep")
        return Intent("power", {"action": "shutdown"}, "Shutting down")
    if _has(t, {"screenshot", "स्क्रीनशॉट"}):
        return Intent("press_keys", {"keys": "win+shift+s"}, "Screenshot tool opened")
    if _has(t, {"desktop", "डेस्कटॉप"}):
        return Intent("press_keys", {"keys": "win+d"}, "Desktop")

    m = re.fullmatch(r"(?:switch to|go back to) (.+)", t)
    if m:
        return Intent("switch_window", {"match": m[1]}, f"Switched to {m[1]}")
    if site:
        if _has(t, {"close", "band", "बंद"}):   # closing asks first: the app might lose unsaved work
            return Intent("window_control", {"match": _WINDOW_NAMES.get(site, site), "action": "close"}, f"Closed {site}")
        if t == site or _has(t, _OPEN_W) or t.startswith("go to ") or _has(t, {"show", "dikhao"}):
            return _open(site)
        return None
    bare = _TRAILING.sub("", t)
    # "jao" only ever goes to a place we know ("youtube pe jao"), or "ruk jao" would be an app called "ruk"
    m = (re.fullmatch(rf"(?:open|launch|start|go to|{_alt(_hi('khol'))}) (\S+(?: \S+){{0,2}})", bare)
         or re.fullmatch(rf"(\S+(?: \S+){{0,2}}) (?:{_alt(_OPEN_W - {'jao', 'जाओ'})})", bare))
    if m and not _has(m[1], {"file", "files", "folder", "document", "photo", "फाइल"}):
        close = difflib.get_close_matches(m[1], [*SITES, *APPS], n=1, cutoff=0.85)   # "calculatr", "crome"
        if close:
            return _open(close[0])
        return Intent("open_app", {"name": m[1]}, f"Opened {m[1]}")
    return None


def understand(text: str, last: str | None = None) -> list[Intent] | None:
    """Everyday sentence -> the steps to run, in order. All of it is understood, or nothing runs."""
    clean = text.replace("’", "'").strip()
    if not clean or len(clean) > 200:
        return None
    for rx, fixed in _SPEECH:
        clean = rx.sub(fixed, clean)
    if _has(_clean(clean.replace("'", "")), _NEGATIVE):
        return None
    whole = _explicit(clean)   # first, so "search tom and jerry" stays one search
    if whole:
        return whole
    steps = []
    for part in _SPLIT.split(clean):
        if not part.strip():
            continue
        found = _explicit(part)
        if found:
            # "flipkart kholo aur shoes search karo": search where we just went
            last = steps[-1].input.get("url", "") if steps else ""
            place = next((n for n in _SEARCH_NAMES if n in last and n.isascii()), None)
            if place and found[0].tool == "web_search" and "google" not in part.lower():
                found[0].input["site"] = _SEARCH_NAMES[place]
                steps.pop()   # the search opens that site anyway
            steps += found
            continue
        step = _clause(part, last)
        if not step:
            return None
        steps.append(step)
    return steps[:5] or None
