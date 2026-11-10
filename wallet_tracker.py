# Wallet tracker - sender en Discord-besked, når en af de mistænkte
# Polymarket-wallets i wallets.txt laver et trade.
# Følger wallet-adressen, så navneskift ikke gør noget (og meldes i Discord).
import json, os, signal, time, requests

MAPPE = os.path.dirname(os.path.abspath(__file__))

# ---- INDSTILLINGER ----
KUN_CS2 = False      # True = kun CS2-markeder
MIN_USD = 0          # ignorer trades under dette beløb (i $)
INTERVAL = 5         # sekunder mellem hver runde
# -----------------------

API = "https://data-api.polymarket.com/v2/activity"  # v1 blev lukket nov. 2026
STATE = os.path.join(MAPPE, "seen.json")


def laes_webhook():
    url = (os.environ.get("DISCORD_WEBHOOK_WALLETS") or open(
        os.path.join(MAPPE, "webhook.txt"), encoding="utf-8").read()).strip()
    if not url.startswith("https://"):
        raise SystemExit("Indsæt din Discord webhook-URL i webhook.txt først.")
    return url


def laes_wallets():
    """Læser wallets.txt. Format pr. linje:  0xadresse  note"""
    wallets = {}
    # På GitHub ligger listen i den hemmelige variabel WALLETS (så den ikke er offentlig)
    tekst = os.environ.get("WALLETS") or open(os.path.join(MAPPE, "wallets.txt"), encoding="utf-8").read()
    # Ekstra konti kan ligge i den hemmelige variabel WALLETS_EXTRA (samme format)
    tekst += "\n" + os.environ.get("WALLETS_EXTRA", "")
    for linje in tekst.splitlines():
        linje = linje.strip()
        if not linje or linje.startswith("#"):
            continue
        dele = linje.split(None, 1)
        adr = dele[0].lower()
        if adr.startswith("0x") and len(adr) == 42:
            wallets[adr] = dele[1] if len(dele) > 1 else ""
        else:
            print("springer over (ikke en wallet-adresse):", linje)
    return wallets


# seen = trades vi allerede har set, seeded = wallets vi har hentet første gang,
# names = sidste kendte Polymarket-navn pr. wallet
if os.path.exists(STATE):
    d = json.load(open(STATE, encoding="utf-8"))
else:
    d = {}
seen = set(d.get("seen", []))
seeded = set(d.get("seeded", []))
names = d.get("names", {})
status_id = d.get("status_id")  # id på bot-status-beskeden i Discord


def gem():
    json.dump({"seen": list(seen)[-20000:], "seeded": list(seeded), "names": names,
               "status_id": status_id},
              open(STATE, "w", encoding="utf-8"))


def post(webhook, payload, forsoeg=0):
    r = requests.post(webhook, json=payload, timeout=10)
    if r.status_code == 429 and forsoeg < 5:
        time.sleep(r.json().get("retry_after", 1))
        return post(webhook, payload, forsoeg + 1)
    if r.status_code >= 300:
        print("DISCORD AFVISTE BESKEDEN:", r.status_code, r.text[:300])
        # Prøv igen med en helt simpel tekstbesked, så alarmen ikke går tabt
        if payload.get("embeds"):
            e = payload["embeds"][0]
            felter = " | ".join(f"{f['name']}: {f['value']}" for f in e.get("fields", []))
            simpel = {"username": payload.get("username"), "content": (payload.get("content") or "")
                      + f"\n**{e.get('title', '')}**\n{felter}\n{e.get('url', '')}",
                      "allowed_mentions": payload.get("allowed_mentions", {})}
            r2 = requests.post(webhook, json=simpel, timeout=10)
            print("Simpel besked:", r2.status_code, r2.text[:200])


def hent(wallet):
    r = requests.get(API, params={"user": wallet, "type": "TRADE", "limit": 50}, timeout=10)
    r.raise_for_status()
    # v2 bruger snake_case-navne - oversæt til de navne resten af koden bruger
    navne = {"transaction_hash": "transactionHash", "token_id": "asset", "usdc_size": "usdcSize",
             "event_slug": "eventSlug", "condition_id": "conditionId", "proxy_wallet": "proxyWallet"}
    return [{navne.get(k, k): v for k, v in t.items()} for t in r.json().get("data") or []]


def visningsnavn(wallet, note):
    navn = names.get(wallet) or wallet[:6] + "…" + wallet[-4:]
    return f"{navn} ({note})" if note else navn


def send_trade(webhook, wallet, note, gruppe, test=False):
    t = gruppe[0]
    usd = sum(x.get("usdcSize", 0) or 0 for x in gruppe)
    shares = sum(x.get("size", 0) or 0 for x in gruppe)
    pris = usd / shares if shares else (t.get("price") or 0)
    kob = t.get("side") == "BUY"
    navn = names.get(wallet) or t.get("name") or note or (wallet[:6] + "…" + wallet[-4:])
    side = str(t.get("outcome", "?"))
    profil = f"https://polymarket.com/profile/{wallet}"
    marked = f"https://polymarket.com/event/{t.get('eventSlug', '')}"
    tx = t.get("transactionHash", "")

    felter = [
        {"name": "💰 Beløb", "value": f"**${usd:,.2f}**", "inline": True},
        {"name": "🎯 Side", "value": f"**{side}**", "inline": True},
        {"name": "📈 Pris", "value": f"{pris*100:.1f}¢  ·  odds {1/pris:.2f}" if pris else "-", "inline": True},
    ]
    if kob and shares:
        felter.append({"name": "💸 Mulig gevinst", "value": f"${shares - usd:,.2f}", "inline": True})
    felter.append({"name": "🧾 Handler", "value": str(len(gruppe)), "inline": True})
    felter.append({"name": "👤 Wallet", "value": f"`{wallet[:6]}…{wallet[-4:]}`", "inline": True})
    links = f"[Profil]({profil})  ·  [Marked]({marked})"
    if tx:
        links += f"  ·  [Transaktion](https://polygonscan.com/tx/{tx})"
    felter.append({"name": "🔗 Links", "value": links, "inline": False})

    embed = {
        "author": {"name": f"🚨 SUSSY BET  ·  {navn}", "url": profil},
        "title": t.get("title", "?"),
        "url": marked,
        "description": f"**{navn}** {'købte' if kob else 'solgte'} **{side}** for **${usd:,.0f}**",
        "color": 0xE01E1E,  # altid rød alarm
        "fields": felter,
        "footer": {"text": "Sussytracker v2  ·  322 | Match Watch" + ("  ·  TEST" if test else "")},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t.get("timestamp", time.time()))),
    }
    if t.get("icon"):
        embed["thumbnail"] = {"url": t["icon"]}
    if test:
        indhold = "🧪 **Test af alarm** - sådan ser en alarm ud (ingen @everyone ved test)"
        mentions = {"parse": []}
    else:
        indhold = f"@everyone 🚨 **{navn}** har lagt et bet på **{side}** - ${usd:,.0f}"
        mentions = {"parse": ["everyone"]}
    post(webhook, {"username": "Sussytracker v2", "content": indhold,
                   "allowed_mentions": mentions, "embeds": [embed]})


def tjek_navn(webhook, wallet, note, trades):
    """Melder i Discord, hvis wallet'en har skiftet navn på Polymarket."""
    if not trades:
        return
    nyt = trades[0].get("name") or trades[0].get("pseudonym")
    if not nyt:
        return
    gammelt = names.get(wallet)
    names[wallet] = nyt
    if gammelt and gammelt != nyt:
        post(webhook, {"username": "Sussytracker v2", "embeds": [{
            "author": {"name": "🔄 NAVNESKIFT"},
            "title": f"{gammelt}  ➜  {nyt}",
            "url": f"https://polymarket.com/profile/{wallet}",
            "description": f"Samme wallet, nyt navn. Vi følger den stadig.\n`{wallet}`"
                           + (f"\nNote: {note}" if note else ""),
            "color": 0xF1C40F,
            "footer": {"text": "Sussytracker v2  ·  322 | Match Watch"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }]})
        print(time.strftime("%H:%M:%S"), "navneskift:", gammelt, "->", nyt)


def tjek(webhook, wallet, note):
    trades = hent(wallet)
    tjek_navn(webhook, wallet, note, trades)
    nye = [t for t in trades if t.get("transactionHash", "") + t.get("asset", "") not in seen]
    for t in nye:
        seen.add(t.get("transactionHash", "") + t.get("asset", ""))

    # Første gang vi ser en wallet: gem dens gamle trades uden at spamme Discord.
    if wallet not in seeded:
        seeded.add(wallet)
        print(f"Følger nu {visningsnavn(wallet, note)} ({len(trades)} gamle trades sprunget over)")
        return

    grupper = {}
    for t in sorted(nye, key=lambda x: x.get("timestamp", 0)):
        if KUN_CS2 and not t.get("slug", "").startswith("cs2-"):
            continue
        grupper.setdefault((t.get("conditionId"), t.get("outcome"), t.get("side")), []).append(t)
    for g in grupper.values():
        if sum(x.get("usdcSize", 0) for x in g) >= MIN_USD:
            send_trade(webhook, wallet, note, g)
            print(time.strftime("%H:%M:%S"), visningsnavn(wallet, note), g[0].get("side"), g[0].get("title"))


# ---- BOT STATUS (kanalen #bot-status) ----
STATUS_HOOK = os.environ.get("DISCORD_WEBHOOK_STATUS", "").strip()
STATUS_HVER = 60  # sekunder mellem opdateringer
sidst_status = 0


def opdater_status(wallets, tilstand="aktiv"):
    """Holder én besked i #bot-status opdateret: kører botten, og hvem overvåges."""
    global status_id, sidst_status
    if not STATUS_HOOK.startswith("https://"):
        return
    sidst_status = time.time()
    nu = int(time.time())
    if tilstand == "aktiv":
        titel, farve = "🟢  SUSSYTRACKER V2 · ACTIVE", 0x2ECC71
        tekst = f"Botten kører og tjekker alle konti hvert {INTERVAL}. sekund."
    elif tilstand == "skifter":
        titel, farve = "🟡  SUSSYTRACKER V2 · SKIFTER OMGANG", 0xF1C40F
        tekst = "Botten starter en ny omgang - er tilbage om et øjeblik."
    else:
        titel, farve = "🔴  SUSSYTRACKER V2 · STOPPET", 0xE01E1E
        tekst = "Botten kører ikke lige nu."
    linjer = [f"{i}. [{names.get(w) or note or w[:6] + '…' + w[-4:]}](https://polymarket.com/profile/{w})"
              for i, (w, note) in enumerate(wallets.items(), 1)]
    # Discord tillader max 1024 tegn pr. felt - del listen op i flere felter
    bidder, bid = [], ""
    for linje in linjer:
        if bid and len(bid) + 1 + len(linje) > 1024:
            bidder.append(bid)
            bid = ""
        bid = (bid + "\n" + linje) if bid else linje
    if bid:
        bidder.append(bid)
    felter_status = [{"name": f"👀 Overvåger {len(wallets)} konti" if n == 0 else "\u200b",
                      "value": v, "inline": False}
                     for n, v in enumerate(bidder or ["Ingen konti på listen"])]
    embed = {
        "title": titel,
        "description": f"{tekst}\n\n**Sidst tjekket:** <t:{nu}:R>  (<t:{nu}:T>)",
        "color": farve,
        "fields": felter_status,
        "footer": {"text": "Står 'sidst tjekket' til mere end 10 min siden, er botten stoppet  ·  322 | Match Watch"},
    }
    payload = {"username": "Sussytracker v2 · status", "embeds": [embed]}
    try:
        if status_id:
            r = requests.patch(f"{STATUS_HOOK}/messages/{status_id}", json=payload, timeout=10)
            if r.ok:
                return
            if r.status_code != 404:
                print("bot-status kunne ikke opdateres:", r.status_code, r.text[:200])
                return
        r = requests.post(STATUS_HOOK + "?wait=true", json=payload, timeout=10)
        if r.ok:
            status_id = r.json().get("id")
            gem()
        else:
            print("bot-status kunne ikke sendes:", r.status_code, r.text[:200])
    except Exception as e:
        print("fejl ved bot-status:", e)


def _stop(*_):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _stop)


# På GitHub kører hver omgang i max ~5,7 timer, derefter tager den næste over.
STOP = time.time() + float(os.environ.get("RUN_SECONDS", "inf"))

webhook = laes_webhook()
tjek_hook = requests.get(webhook, timeout=10)
print("Webhook-tjek:", tjek_hook.status_code, "OK" if tjek_hook.ok else tjek_hook.text[:200])
if os.environ.get("TEST_ALARM") == "true":
    send_trade(webhook, "0xaaad37f3bbb45af95818e20e554f8b21371f29e0", "swiftfoxx", [{
        "title": "Counter-Strike: DNK vs Wingman (BO3) - Exort Fiesta Group Stage",
        "eventSlug": "cs2-dnk2-wing-2026-11-02", "outcome": "Wingman", "side": "BUY",
        "usdcSize": 72.0, "size": 200.0, "transactionHash": "",
        "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/counter-strike-image-16c415c538.png",
        "timestamp": time.time()}], test=True)
    print("Testalarm sendt")
print("Wallet tracker kører... (luk vinduet for at stoppe)")
print("Tilføj/fjern wallets i wallets.txt - det virker uden genstart.")
wallets = {}
slut = "stoppet"
try:
    while time.time() < STOP:
        try:
            wallets = laes_wallets()
        except Exception as e:
            print("kunne ikke læse wallet-listen:", e)
            wallets = {}
        for w, note in wallets.items():
            try:
                tjek(webhook, w, note)
            except Exception as e:
                print("fejl ved", w, ":", e)
        gem()
        if time.time() - sidst_status >= STATUS_HVER:
            opdater_status(wallets)
        time.sleep(INTERVAL)
    slut = "skifter"  # tiden er gået - næste omgang starter af sig selv
finally:
    opdater_status(wallets, slut)
    gem()
