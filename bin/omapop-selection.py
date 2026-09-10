#!/usr/bin/python3 -I
"""Read the Wayland primary selection (or the clipboard), bounded, as one JSON line.

usage: omapop-selection.py [--clipboard] [--max-bytes N] [--html] [--clipboard-text]

The shell never reads a selection directly: this helper is the boundary. It
streams at most N+1 bytes from wl-paste, kills the producer the moment the
limit is crossed, applies a deadline to every child, and emits a single JSON
object that the caller caps again before parsing.

Output (always one line):
  {"ok": true, "text": "...", "html": "..."|null, "types": [...],
   "data": {"urls": [...], "nonHttpUrls": [...], "emails": [...], "paths": [...]},
   "isUrl": bool, "snippet": {"name": "..."}|null, "bytes": n}
  {"ok": false, "reason": "empty"|"no-text"|"too-large"|"timeout"|"error"}
"""
import json
import os
import re
import select
import subprocess
import sys
import time

WL_PASTE = "/usr/bin/wl-paste"
TYPES_LIMIT = 16384
DEADLINE_S = 2.5
TEXT_TYPES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT")
HTML_TYPES = ("text/html", "text/html;charset=utf-8")
SNIPPET_LIMIT = 5000
SENSITIVE_HINT = "x-kde-passwordmanagerhint"
MAX_URLS = 200
MAX_URL_LENGTH = 8192  # QML's per-string limit, including the inferred scheme.
MAX_NON_HTTP_URLS = 50
MAX_EMAILS = 200
MAX_PATHS = 50

# Schemes Open Link recognises besides http(s), for input.data.nonHttpUrls.
NON_HTTP_SCHEMES = ("bluesky", "craftdocs", "evernote", "ftp", "hook", "message", "omnifocus", "spotify", "x-devonthink-item")

# IANA root-zone snapshot, bundled so selection detection never needs the network.
# https://data.iana.org/TLD/tlds-alpha-by-domain.txt
# Version 2026091000, Last Updated Thu Sep 10 07:07:01 2026 UTC
# SHA-256: a21f8a02b6b3e320cc0e173045481bc62c882b00805ae1cc5cbda9744a5e3b44
TLDS = frozenset("""
aaa aarp abb abbott abbvie abc able abogado abudhabi ac academy accenture accountant accountants aco actor ad
ads adult ae aeg aero aetna af afl africa ag agakhan agency ai aig airbus airforce airtel akdn al alibaba
alipay allfinanz allstate ally alsace alstom am amazon americanexpress americanfamily amex amfam amica
amsterdam analytics android anquan anz ao aol apartments app apple aq aquarelle ar arab aramco archi army arpa
art arte as asda asia associates at athleta attorney au auction audi audible audio auspost author auto autos
aw aws ax axa az azure ba baby baidu banamex band bank bar barcelona barclaycard barclays barefoot bargains
baseball basketball bauhaus bayern bb bbc bbt bbva bcg bcn bd be beats beauty beer berlin best bestbuy bet bf
bg bh bharti bi bible bid bike bing bingo bio biz bj black blackfriday blockbuster blog bloomberg blue bm bms
bmw bn bnpparibas bo boats boehringer bofa bom bond boo book booking bosch bostik boston bot boutique box br
bradesco bridgestone broadway broker brother brussels bs bt build builders business buy buzz bv bw by bz bzh
ca cab cafe cal call calvinklein cam camera camp canon capetown capital capitalone car caravan cards care
career careers cars casa case cash casino cat catering catholic cba cbn cbre cc cd center ceo cern cf cfa cfd
cg ch chanel channel charity chase chat cheap chintai christmas chrome church ci cipriani circle cisco citadel
citi citic city ck cl claims cleaning click clinic clinique clothing cloud club clubmed cm cn co coach codes
coffee college cologne com commbank community company compare computer comsec condos construction consulting
contact contractors cooking cool coop corsica country coupon coupons courses cpa cr credit creditcard
creditunion cricket crown crs cruise cruises cu cuisinella cv cw cx cy cymru cyou cz dad dance data date
dating datsun day dclk dds de deal dealer deals degree delivery dell deloitte delta democrat dental dentist
desi design dev dhl diamonds diet digital direct directory discount discover dish diy dj dk dm dnp do docs
doctor dog domains dot download drive dtv dubai dupont durban dvag dvr dz earth eat ec eco edeka edu education
ee eg email emerck energy engineer engineering enterprises epson equipment er ericsson erni es esq estate et
eu eurovision eus events exchange expert exposed express extraspace fage fail fairwinds faith family fan fans
farm farmers fashion fast fedex feedback ferrari ferrero fi fidelity fido film final finance financial fire
firestone firmdale fish fishing fit fitness fj fk flickr flights flir florist flowers fly fm fo foo food
football ford forex forsale forum foundation fox fr free fresenius frl frogans frontier ftr fujitsu fun fund
furniture futbol fyi ga gal gallery gallo gallup game games gap garden gay gb gbiz gd gdn ge gea gent genting
george gf gg ggee gh gi gift gifts gives giving gl glass gle global globo gm gmail gmbh gmo gmx gn godaddy
gold goldpoint golf goodyear goog google gop got gov gp gq gr grainger graphics gratis green gripe grocery
group gs gt gu gucci guge guide guitars guru gw gy hair hamburg hangout haus hbo hdfc hdfcbank health
healthcare help helsinki here hermes hiphop hisamitsu hitachi hiv hk hkt hm hn hockey holdings holiday
homedepot homegoods homes homesense honda horse hospital host hosting hot hotels hotmail house how hr hsbc ht
hu hughes hyatt hyundai ibm icbc ice icu id ie ieee ifm ikano il im imamat imdb immo immobilien in inc
industries infiniti info ing ink institute insurance insure int international intuit investments io ipiranga
iq ir irish is ismaili ist istanbul it itau itv jaguar java jcb je jeep jetzt jewelry jio jll jm jmp jnj jo
jobs joburg jot joy jp jpmorgan jprs juegos juniper kaufen kddi ke kerryhotels kerryproperties kfh kg kh ki
kia kids kim kindle kitchen kiwi km kn koeln komatsu kosher kp kpmg kpn kr krd kred kuokgroup kw ky kyoto kz
la lacaixa lamborghini lamer land landrover lanxess lasalle lat latino latrobe law lawyer lb lc lds lease
leclerc lefrak legal lego lexus lgbt li lidl life lifeinsurance lifestyle lighting like lilly limited limo
lincoln link live living lk llc llp loan loans locker locus lol london lotte lotto love lpl lplfinancial lr ls
lt ltd ltda lu lundbeck luxe luxury lv ly ma madrid maif maison makeup man management mango map market
marketing markets marriott marshalls mattel mba mc mckinsey md me med media meet melbourne meme memorial men
menu merck merckmsd mg mh miami microsoft mil mini mint mit mitsubishi mk ml mlb mls mm mma mn mo mobi mobile
moda moe moi mom monash money monster mormon mortgage moscow moto motorcycles mov movie mp mq mr ms msd mt mtn
mtr mu museum music mv mw mx my mz na nab nagoya name navy nba nc ne nec net netbank netflix network neustar
new news next nextdirect nexus nf nfl ng ngo nhk ni nico nike nikon ninja nissan nissay nl no nokia norton now
nowruz nowtv np nr nra nrw ntt nu nyc nz obi observer office okinawa olayan olayangroup ollo om omega one ong
onl online ooo open oracle orange org organic origins osaka otsuka ott ovh pa page panasonic paris pars
partners parts party pay pccw pe pet pf pfizer pg ph pharmacy phd philips phone photo photography photos
physio pics pictet pictures pid pin ping pink pioneer pizza pk pl place play playstation plumbing plus pm pn
pnc pohl poker politie porn post pr praxi press prime pro prod productions prof progressive promo properties
property protection pru prudential ps pt pub pw pwc py qa qpon quebec quest racing radio re read realestate
realtor realty recipes red redumbrella rehab reise reisen reit reliance ren rent rentals repair report
republican rest restaurant review reviews rexroth rich richardli ricoh ril rio rip ro rocks rodeo rogers room
rs rsvp ru rugby ruhr run rw rwe ryukyu sa saarland safe safety sakura sale salon samsclub samsung sandvik
sandvikcoromant sanofi sap sarl sas save saxo sb sbi sbs sc scb schaeffler schmidt scholarships school schule
schwarz science scot sd se search seat secure security seek select sener services seven sew sex sexy sfr sg sh
shangrila sharp shell shia shiksha shoes shop shopping shouji show si silk sina singles site sj sk ski skin
sky skype sl sling sm smart smile sn sncf so soccer social softbank software sohu solar solutions song sony
soy spa space sport spot sr srl ss st stada staples star statebank statefarm stc stcgroup stockholm storage
store stream studio study style su sucks supplies supply support surf surgery suzuki sv swatch swiss sx sy
sydney systems sz tab taipei talk taobao target tatamotors tatar tattoo tax taxi tc tci td tdk team tech
technology tel temasek tennis teva tf tg th thd theater theatre tiaa tickets tienda tips tires tirol tj tjmaxx
tjx tk tkmaxx tl tm tmall tn to today tokyo tools top toray toshiba total tours town toyota toys tr trade
trading training travel travelers travelersinsurance trust trv tt tube tui tunes tushu tv tvs tw tz ua ubank
ubs ug uk unicom university uno uol ups us uy uz va vacations vana vanguard vc ve vegas ventures verisign
versicherung vet vg vi viajes video vig viking villas vin vip virgin visa vision viva vivo vlaanderen vn vodka
volvo vote voting voto voyage vu wales walmart walter wang wanggou watch watches weather weatherchannel web
webcam weber website wed wedding weibo weir wf whoswho wien wiki williamhill win windows wine winners wme
woodside work works world wow ws wtc wtf xbox xerox xihuan xin xn--11b4c3d xn--1ck2e1b xn--1qqw23a xn--2scrj9c
xn--30rr7y xn--3bst00m xn--3ds443g xn--3e0b707e xn--3hcrj9c xn--3pxu8k xn--42c2d9a xn--45br5cyl xn--45brj9c
xn--45q11c xn--4dbrk0ce xn--4gbrim xn--54b7fta0cc xn--55qw42g xn--55qx5d xn--5su34j936bgsg xn--5tzm5g
xn--6frz82g xn--6qq986b3xl xn--80adxhks xn--80ao21a xn--80aqecdr1a xn--80asehdb xn--80aswg xn--8y0a063a
xn--90a3ac xn--90ae xn--90ais xn--9dbq2a xn--9et52u xn--9krt00a xn--b4w605ferd xn--bck1b9a5dre4c xn--c1avg
xn--c2br7g xn--cck2b3b xn--cckwcxetd xn--cg4bki xn--clchc0ea0b2g2a9gcd xn--czr694b xn--czrs0t xn--czru2d
xn--d1acj3b xn--d1alf xn--e1a4c xn--eckvdtc9d xn--efvy88h xn--fct429k xn--fhbei xn--fiq228c5hs xn--fiq64b
xn--fiqs8s xn--fiqz9s xn--fjq720a xn--flw351e xn--fpcrj9c3d xn--fzc2c9e2c xn--fzys8d69uvgm xn--g2xx48c
xn--gckr3f0f xn--gecrj9c xn--gk3at1e xn--h2breg3eve xn--h2brj9c xn--h2brj9c8c xn--hxt814e xn--i1b6b1a6a2e
xn--imr513n xn--io0a7i xn--j1aef xn--j1amh xn--j6w193g xn--jlq480n2rg xn--jvr189m xn--kcrx77d1x4a xn--kprw13d
xn--kpry57d xn--kput3i xn--l1acc xn--lgbbat1ad8j xn--mgb9awbf xn--mgba3a3ejt xn--mgba3a4f16a xn--mgba7c0bbn0a
xn--mgbaam7a8h xn--mgbab2bd xn--mgbah1a3hjkrd xn--mgbai9azgqp6j xn--mgbayh7gpa xn--mgbbh1a xn--mgbbh1a71e
xn--mgbc0a9azcg xn--mgbca7dzdo xn--mgbcpq6gpa1a xn--mgberp4a5d4ar xn--mgbgu82a xn--mgbi4ecexp xn--mgbpl2fh
xn--mgbt3dhd xn--mgbtx2b xn--mgbx4cd0ab xn--mix891f xn--mk1bu44c xn--mxtq1m xn--ngbc5azd xn--ngbe9e0a
xn--ngbrx xn--node xn--nqv7f xn--nqv7fs00ema xn--nyqy26a xn--o3cw4h xn--ogbpf8fl xn--otu796d xn--p1acf
xn--p1ai xn--pgbs0dh xn--pssy2u xn--q7ce6a xn--q9jyb4c xn--qcka1pmc xn--qxa6a xn--qxam xn--rhqv96g xn--rovu88b
xn--rvc1e0am3e xn--s9brj9c xn--ses554g xn--t60b56a xn--tckwe xn--tiq49xqyj xn--unup4y xn--vermgensberater-ctb
xn--vermgensberatung-pwb xn--vhquv xn--vuq861b xn--w4r85el8fhu5dnra xn--w4rs40l xn--wgbh1c xn--wgbl6a
xn--xhq521b xn--xkc2al3hye2a xn--xkc2dl3a5ee0h xn--y9a3aq xn--yfro4i67o xn--ygbi2ammx xn--zfr164b xxx xyz
yachts yahoo yamaxun yandex ye yodobashi yoga yokohama you youtube yt yun za zappos zara zero zip zm zone
zuerich zw
""".split())


def fail(reason):
    sys.stdout.write(json.dumps({"ok": False, "reason": reason}) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def bounded_run(argv, limit, deadline_s):
    """Run argv, return (status, bytes) where status is 'ok', 'too-large' or 'timeout'.

    Reads incrementally; kills the child as soon as more than `limit` bytes
    arrive or the deadline passes. stderr goes to /dev/null so it can never
    become a second unbounded buffer.
    """
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return "error", b""
    chunks = []
    total = 0
    status = "ok"
    end = time.monotonic() + deadline_s
    fd = proc.stdout.fileno()
    try:
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                status = "timeout"
                break
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                status = "too-large"
                break
            chunks.append(chunk)
    finally:
        if status != "ok":
            proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)
        proc.stdout.close()
    return status, b"".join(chunks)


def list_types(selection_args):
    status, data = bounded_run([WL_PASTE, *selection_args, "--list-types"], TYPES_LIMIT, DEADLINE_S)
    if status != "ok":
        return []
    out = []
    for line in data.decode("utf-8", "replace").split("\n"):
        line = line.strip()
        if line and len(line) <= 200 and line not in out:
            out.append(line)
    return out


def read_type(selection_args, mime, limit):
    status, data = bounded_run([WL_PASTE, *selection_args, "--no-newline", "--type", mime], limit + 1, DEADLINE_S)
    if status != "ok":
        return status, None
    if len(data) > limit:
        return "too-large", None
    return "ok", data.decode("utf-8", "replace")


URL_RE = re.compile(r"""(?<![\w@/.])(https?://[^\s<>"'`\]\[)(]+[^\s<>"'`\]\[)(.,;:!?])""", re.IGNORECASE)
BARE_URL_RE = re.compile(r"""(?<![\w@/.:+-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,63}|xn--[a-z0-9-]{1,59})(?![\w-]|\.[\w.-])(?::(\d{1,5}))?(?:[/?#][^\s<>"'`\]\[)(]*)?)(?![\w@:-])""", re.IGNORECASE)
NON_HTTP_RE = re.compile(r"(?<![\w])((?:%s):[^\s<>\"'`]+)" % "|".join(re.escape(s) for s in NON_HTTP_SCHEMES), re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24})(?![\w-])")
PATH_TOKEN_RE = re.compile(r"(?:(?<=\s)|^)(~?/[^\s\"'`<>|]+)")


def strip_trailing(url):
    return url.rstrip(".,;:!?)")


def detect(text):
    urls = []
    seen = set()
    # Enforce the output limits while collecting, not after scanning every
    # match. In particular, bare-URL suffix checks must never walk an unbounded
    # list. Explicit URLs still take priority over bare domains in the output.
    for m in URL_RE.finditer(text):
        u = strip_trailing(m.group(1))
        key = u.lower()
        if u and key not in seen:
            seen.add(key)
            urls.append(u)
            if len(urls) == MAX_URLS:
                break
    if len(urls) < MAX_URLS:
        for m in BARE_URL_RE.finditer(text):
            if m.end(1) - m.start(1) > MAX_URL_LENGTH - len("https://"):
                continue
            whole = strip_trailing(m.group(1))
            tld = m.group(2).lower()
            host = re.split(r"[:/?#]", whole, maxsplit=1)[0]
            if len(host) > 253 or tld not in TLDS:
                continue
            if m.group(3) is not None and not 1 <= int(m.group(3)) <= 65535:
                continue
            candidate = "https://" + whole
            key = candidate.lower()
            whole_key = whole.lower()
            if key not in seen and not any(key.endswith(u.lower()[len(u) - len(whole):]) and whole_key in u.lower() for u in urls):
                seen.add(key)
                urls.append(candidate)
                if len(urls) == MAX_URLS:
                    break
    non_http = []
    seen_non_http = set()
    for m in NON_HTTP_RE.finditer(text):
        u = strip_trailing(m.group(1))
        if u not in seen_non_http:
            seen_non_http.add(u)
            non_http.append(u)
            if len(non_http) == MAX_NON_HTTP_URLS:
                break
    emails = []
    seen_emails = set()
    for m in EMAIL_RE.finditer(text):
        e = m.group(1)
        if e not in seen_emails:
            seen_emails.add(e)
            emails.append(e)
            if len(emails) == MAX_EMAILS:
                break
    paths = []
    candidates = []
    stripped = text.strip()
    if stripped and "\n" not in stripped and len(stripped) <= 4096:
        candidates.append(stripped)
    if len(text) <= 65536:
        for m in PATH_TOKEN_RE.finditer(text):
            candidates.append(m.group(1))
            if len(candidates) == 64:
                break
    for c in candidates:
        c = c.rstrip(".,;:")
        if not (c.startswith("/") or c.startswith("~/") or c == "~"):
            continue
        try:
            expanded = os.path.expanduser(c)
            if os.path.exists(expanded):
                normalized = os.path.normpath(expanded)
                if normalized not in paths:
                    paths.append(normalized)
                    if len(paths) == MAX_PATHS:
                        break
        except (OSError, ValueError):
            continue
    is_url = False
    if urls and len(urls) == 1 and stripped:
        only = strip_trailing(stripped)
        is_url = only.lower() == urls[0].lower() or ("https://" + only).lower() == urls[0].lower()
    return {"urls": urls, "nonHttpUrls": non_http, "emails": emails, "paths": paths}, is_url


SNIPPET_HEAD_RE = re.compile(r"^\s*(?:(//|--|#)\s*)?#\s?popclip\b", re.IGNORECASE)
SNIPPET_NAME_RE = re.compile(r"""^\s*(?:(?://|--|#)\s*)?(?:"name"|'name'|name)\s*:\s*(.+?)\s*,?\s*$""", re.IGNORECASE | re.MULTILINE)
FLOW_NAME_RE = re.compile(r"""(?:"name"|'name'|\bname)\s*:\s*("[^"]*"|'[^']*'|[^,}\n]+)""", re.IGNORECASE)


def snippet_info(text):
    if len(text) > SNIPPET_LIMIT or not SNIPPET_HEAD_RE.match(text):
        return None
    name = None
    m = SNIPPET_NAME_RE.search(text)
    if m:
        name = m.group(1)
    else:
        m = FLOW_NAME_RE.search(text)
        if m:
            name = m.group(1)
    if name:
        name = name.strip().strip("\"'").strip()
        if name.startswith("{"):
            name = None
    if name and len(name) > 64:
        name = name[:64]
    return {"name": name or ""}


def read_clipboard(max_bytes):
    """The regular clipboard, for canPaste and pasteboard.text. Never fatal."""
    types = list_types([])
    if not types:
        return {"hasText": False, "text": ""}
    text_type = next((t for t in TEXT_TYPES if t in types), None)
    if text_type is None:
        text_type = next((t for t in types if t.lower().startswith("text/plain")), None)
    if text_type is None:
        return {"hasText": False, "text": "", "types": types[:16]}
    # Password managers mark a copied secret with this hint. Paste still works
    # (the app receives Ctrl+V); the secret itself never enters the shell or an
    # extension's pasteboard.text.
    if any(t.lower().startswith(SENSITIVE_HINT) for t in types):
        return {"hasText": True, "text": "", "sensitive": True}
    status, text = read_type([], text_type, max_bytes)
    if status != "ok":
        return {"hasText": True, "text": "", "truncated": True}
    return {"hasText": len(text) > 0, "text": text}


def main(argv):
    max_bytes = 262144
    want_html = False
    want_clipboard = False
    clipboard = False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--max-bytes" and i + 1 < len(argv):
            try:
                max_bytes = max(1024, min(int(argv[i + 1]), 16 * 1024 * 1024))
            except ValueError:
                fail("error")
            i += 2
            continue
        if a == "--html":
            want_html = True
        elif a == "--clipboard":
            clipboard = True
        elif a == "--clipboard-text":
            want_clipboard = True
        i += 1
    selection_args = [] if clipboard else ["--primary"]
    clip = read_clipboard(max_bytes) if want_clipboard else None

    def fail_with(reason):
        out = {"ok": False, "reason": reason}
        if clip is not None:
            out["clipboard"] = clip
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        sys.exit(0)

    types = list_types(selection_args)
    if not types:
        fail_with("empty")
    text_type = next((t for t in TEXT_TYPES if t in types), None)
    if text_type is None:
        text_type = next((t for t in types if t.lower().startswith("text/plain")), None)
    if text_type is None:
        fail_with("no-text")
    status, text = read_type(selection_args, text_type, max_bytes)
    if status != "ok":
        fail_with(status)
    if clipboard:
        sys.stdout.write(json.dumps({"ok": True, "text": text, "types": types[:32]}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return
    html = None
    if want_html:
        html_type = next((t for t in HTML_TYPES if t in types), None)
        if html_type is None:
            html_type = next((t for t in types if t.lower().startswith("text/html")), None)
        if html_type is not None:
            hstatus, html = read_type(selection_args, html_type, max_bytes)
            if hstatus != "ok":
                html = None
    data, is_url = detect(text)
    result = {
        "ok": True,
        "text": text,
        "html": html,
        "types": types[:32],
        "data": data,
        "isUrl": is_url,
        "snippet": snippet_info(text),
        "bytes": len(text.encode("utf-8")),
    }
    if clip is not None:
        result["clipboard"] = clip
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BrokenPipeError:
        pass
    except Exception:  # noqa: BLE001 - the caller only ever sees a shape it can validate
        fail("error")
