# Sussy kontoer tracker

Sender en rød alarm med @everyone i Discord-kanalen #sussy-kontoer, hver gang en af de overvågede Polymarket-wallets lægger et bet.

Kører gratis på GitHub Actions døgnet rundt (fanen **Actions**).

- **Wallet-listen** ligger i Settings → Secrets and variables → Actions → `WALLETS` (én wallet pr. linje: `0xadresse  navn`).
- **Discord-webhook** ligger i `DISCORD_WEBHOOK_WALLETS`.
- Ændringer i listen gælder fra næste omgang (højst ca. 6 timer), eller med det samme hvis man trykker **Run workflow** under Actions.
