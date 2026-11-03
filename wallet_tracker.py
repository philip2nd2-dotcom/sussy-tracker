# Wallet tracker - sender en Discord-besked, når en af de mistænkte
# Polymarket-wallets i wallets.txt laver et trade.
# Følger wallet-adressen, så navneskift ikke gør noget (og meldes i Discord).
import json, os, time, requests

MAPPE = os.path.dirname(os.path.abspath(__file__))

# ---- INDSTILLINGER ----
KUN_CS2 = False      # True = kun CS2-markeder
MIN_USD = 0          # ignorer trades under dette beløb (i $)
INTERVAL = 5         # sekunder mellem hver runde
# -----------------------

API = "https://data-api.polymarket.com/v2/activity"  # v1 blev lukket nov. 2026
STATE = os.path.join(MAPPE, "seen.json")


def laes_webhook():
    url = os.environ.get("DISCORD_WEBHOOK_WALLETS") or open(
        os.path.join(MAPPE, "webhook.txt"), encoding="utf-8").read().strip()
    if not url.startswith("https://"):
        raise SystemExit("Indsæt din Discord webhook-URL i webhook.txt først.")
    return url


def laes_wallets():
    """Læser wallets.txt. Format pr. linje:  0xadresse  note"""
    wallets = {}
    # På GitHub ligger listen i den hemmelige variabel WALLETS (så den ikke er offentlig)
    tekst = os.environ.get("WALLETS") or open(os.path.join(MAPPE, "wallets.txt"), encoding="utf-8").read()
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


def gem():
    json.dump({"seen": list(seen)[-20000:], "seeded": list(seeded), "names": names},
              open(STATE, "w", encoding="utf-8"))


def post(webhook, payload):
    r = requests.post(webhook, json=payload, timeout=10)
    if r.status_code == 429:
        time.sleep(r.json().get("retry_after", 1))
        post(webhook, payload)


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


def send_trade(webhook, wallet, note, gruppe):
    t = gruppe[0]
    usd = sum(x.get("usdcSize", 0) for x in gruppe)
    shares = sum(x.get("size", 0) for x in gruppe)
    pris = usd / shares if shares else t.get("price", 0)
    kob = t.get("side") == "BUY"
    embed = {
        "title": t.get("title", "?"),
        "url": f"https://polymarket.com/event/{t.get('eventSlug', '')}",
        "color": 0xFF0000,  # altid rød alarm
        "author": {"name": f"{visningsnavn(wallet, note)} {'KØBTE' if kob else 'SOLGTE'}",
                   "url": f"https://polymarket.com/profile/{wallet}"},
        "fields": [
            {"name": "Side", "value": str(t.get("outcome", "?")), "inline": True},
            {"name": "Beløb", "value": f"${usd:,.2f}", "inline": True},
            {"name": "Odds", "value": f"{pris*100:.1f}¢ ({1/pris:.2f})" if pris else "-", "inline": True},
        ],
        "footer": {"text": wallet},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t.get("timestamp", time.time()))),
    }
    if t.get("icon"):
        embed["thumbnail"] = {"url": t["icon"]}
    post(webhook, {
        "username": "Sussy kontoer",
        # @everyone giver en notifikation til alle på serveren
        "content": f"@everyone 🚨 **{visningsnavn(wallet, note)}** har lagt et bet: "
                   f"{'KØB' if kob else 'SALG'} ${usd:,.0f} på {t.get('outcome', '?')}",
        "allowed_mentions": {"parse": ["everyone"]},
        "embeds": [embed],
    })


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
        post(webhook, {"username": "Sussy kontoer", "embeds": [{
            "title": "Navneskift",
            "description": f"**{gammelt}** hedder nu **{nyt}**\nSamme wallet: `{wallet}`"
                           + (f"\nNote: {note}" if note else ""),
            "url": f"https://polymarket.com/profile/{wallet}",
            "color": 0xF1C40F,
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


# På GitHub kører hver omgang i max ~5,7 timer, derefter tager den næste over.
STOP = time.time() + float(os.environ.get("RUN_SECONDS", "inf"))

webhook = laes_webhook()
print("Wallet tracker kører... (luk vinduet for at stoppe)")
print("Tilføj/fjern wallets i wallets.txt - det virker uden genstart.")
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
    time.sleep(INTERVAL)
