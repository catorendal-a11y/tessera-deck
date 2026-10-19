# Agent Deck

Et komplett Stream Deck-system for ESP32-P4 Function EV Board med 1024 × 600
berøringsskjerm. Enheten viser ett stabilt 6 × 3-knapperutenett i fullskjerm.
Windows-programmet håndterer profiler, handlinger, bilder og USB-forbindelsen.

Standardforsiden åpner de mest brukte installerte programmene direkte: Chrome,
ChatGPT, ZCode, Claude, VS Code, GitHub Desktop, Terminal, Utforsker, Discord,
Obsidian, LM Studio, Steam og Xbox. De resterende plassene gir skjermbilde,
flere apper, systemkontroll og lyd av/på. Hjemknappen ligger fast som knapp 18.

## Start

Dobbeltklikk `Agent-Deck.cmd`. Dette åpner terminalprogrammet, som er
hovedprogrammet. Første start oppretter et lokalt Python-miljø og installerer
avhengighetene. Python 3.11 eller nyere kreves.

I terminalen kan du redigere alle 18 knapper, bytte profil og side, starte eller
stoppe USB-verten og åpne den grafiske editoren med **F8**. Den grafiske
editoren kjører lokalt på maskinen og brukes til Elgato-lignende dra og slipp.
Den er et redigeringsvindu for terminalprogrammet, ikke en nettjeneste.

Editoren åpnes som et eget Windows-program med WebView2 og Agent Deck-ikon.
Localhost-serveren er kun den interne motoren og vises ikke som en vanlig
nettleserfane. Hvis WebView2 mangler, brukes standardnettleseren som reserve.

Du kan også åpne den direkte:

```powershell
Agent-Deck.cmd --editor
```

## Knapper og dra og slipp

Den grafiske editoren har disse funksjonene:

- Dra en handling til ett av 18 spor.
- Dra knapper mellom spor for å flytte eller bytte dem.
- Høyreklikk en knapp for å duplisere, kopiere, feste eller tømme den.
- Dupliser hele sider og profiler med ett trykk.
- Legg flere handlinger på samme knapp og sorter rekkefølgen.
- Ta opp hurtigtaster direkte.
- Velg program, fil, mappe eller URL.
- Bruk egne PNG-, JPEG-, GIF- eller WebP-bilder. Bilder skaleres og sendes til
  enheten; animerte GIF/WebP støttes med opptil 12 optimaliserte bilder.
- Velg blant 1 895 medfølgende Lucide-ikoner med søk, favoritter og historikk.
- Fest en knapp slik at den vises på alle sider.
- Lag mapper med tilbake-navigasjon og opptil 16 nivåer.
- Lag knapper med 2–8 tilstander, for eksempel Av/På.
- Juster tittelstørrelse, plassering og fet skrift.
- Angre/gjør om med `Ctrl+Z` / `Ctrl+Shift+Z`, og kopier/lim inn knapper.
- Legg til 119 ferdige handlinger for Windows, vinduer, PowerToys, GitHub Desktop,
  VS Code, nettlesere, møter, medier, redigering, Codex, Claude Code og ZCode uten
  å skrive hurtigtastene selv.
- Opprett komplette profiler fra ti maler: Daglig kontroll, Windows-kontroll,
  Nettleser, Møter, VS Code, GitHub Desktop, PowerToys, Codex, Claude Code og
  ZCode. Maler finnes både i terminalen og
  dra-og-slipp-editoren.
- Åpne **Program** for å la USB-verten starte automatisk ved Windows-innlogging,
  uten å åpne editorvinduet.

## AI-kodeverktøy

De tre AI-profilene styrer verktøyene direkte og inneholder ingen monitor:

- **Codex** starter eller fortsetter Codex CLI og har knapper for ny chat,
  gjenoppta, review, diff, modell, resonnering, plan, status og mål.
- **Claude Code** starter, fortsetter eller gjenopptar Claude Code og har
  knapper for kontekst, modell, tillatelser, plan, sikkerhet og oppgaver.
- **ZCode** åpner den installerte skrivebordsappen og bruker ZCodes offisielle
  Windows-snarveier for oppgaver, paneler, modell, tankenivå og kjøremodus.

Codex- og Claude-malene kjenner igjen både terminalens underprosess og
vindustittel. I profilinnstillingene kan du velge et kjørende program direkte.
Avanserte regler kan skrives som `program.exe`, `process:claude.exe` eller
`title:codex`. Statuslinjen viser når en profil er valgt automatisk.

Startknappene for Codex og Claude Code åpner en ny fane i Windows Terminal i
mappen der Agent Deck kjører. Kommando- og hurtigtastknappene sendes til vinduet
som er aktivt. ZCode-profilen byttes automatisk inn når `ZCode.exe` er aktiv.

Oppsettene følger den offisielle dokumentasjonen for
[Codex-kommandoer](https://developers.openai.com/codex/cli/slash-commands),
[Claude Code-kommandoer](https://code.claude.com/docs/en/commands),
[Claude Code interaktiv modus](https://code.claude.com/docs/en/interactive-mode),
[ZCode-snarveier](https://zcode.z.ai/en/docs/keyboard-shortcuts) og
[ZCode-kommandoer](https://zcode.z.ai/en/docs/commands).

Endringer lagres automatisk etter validering. Oppsettet ligger i
`host/profiles.json`, som opprettes fra `host/profiles.default.json` ved første
start; importer og eksporter profiler fra editoren. Stier i `open`-handlinger
kan bruke miljøvariabler som `%LOCALAPPDATA%`.

## Handlinger

En knapp kan kjøre én eller flere handlinger:

- `hotkey`: hurtigtast eller medietast
- `text`: skriv tekst
- `open`: åpne program, fil, mappe eller URL
- `shell`: kjør kommando
- `http`: kall et HTTP-endepunkt
- `delay`: vent mellom trinn
- `folder` og `back`: naviger i mapper
- `page` og `profile`: bytt side eller profil
- `press`: kjør en annen knapp
- `set`: sett en variabel

Etiketter kan bruke `$(time)`, `$(date)`, `$(profile)`, `$(page)` og
`$(var:navn)`. Profilregler kan automatisk bytte profil ut fra aktivt program.

## USB og fastvare

`host/agent_deckd.py` er eneste eier av USB-porten. Standardporten på denne
maskinen er COM4. COM6 brukes ikke. Ved ny tilkobling sender verten aktiv side,
bilder og kontekst på nytt.

Verten vekker LCD-baklyset ved tilkobling, sideoppdatering og fysisk trykk. Hvis
panelet er svart mens touch fortsatt virker, kan det derfor gjenopprettes uten
å trekke kabelen eller starte Windows på nytt.

Bygg med ESP-IDF 6.1:

```powershell
idf.py -B build/idf6 build
```

Ved manuell oppdatering skal bare applikasjonen skrives til `0x10000`. Det
bevarer bootloader, partisjonstabell og NVS.

## Kontroller

```powershell
host\.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py -v
host\.venv\Scripts\python.exe host\agent_deck_terminal.py --check
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews\deck-only
```

Native-testen rendrer den faktiske LVGL-flaten. Maskinvaretesten
`tests/hardware_smoke.py` kontrollerer COM4 uten å kjøre hurtigtaster eller
andre handlinger på PC-en.

Lucide- og Feather-lisensene ligger i `vendor/lucide/LICENSE`.
