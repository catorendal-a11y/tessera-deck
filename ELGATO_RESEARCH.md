# Elgato Stream Deck: research for Agent Deck

Undersøkt 18.–19. oktober 2026. Offisielle produkt-, hjelpe- og SDK-sider er brukt
for Elgato-funksjoner. Status for Agent Deck er kontrollert mot lokal kildekode.
Dette er et sammenligningsgrunnlag, ikke en påstand om full kompatibilitet.

## Hva folk faktisk bruker

Elgatos standardprofil inkluderer skjermbilde, volum og appstart. Marketplace
fremhever i tillegg lydmiks, vindusplassering, møter, virtuelle skrivebord,
systemstatus og appspesifikke profiler. Elgatos offisielle ChatGPT & Codex-plugin
prioriterer aktivitet, ny chat, prompt/steering, stopp, modell, resonnering, bruk
og panelbytte.

Brukeroppsett gjentar det samme mønsteret: mediekontroll, åpning av apper og
mapper, skjermbilder, utklippshistorikk, virtuelle skrivebord, vindusplassering,
møteknapper, faste hjemknapper og multihandlinger som starter en arbeidsøkt.
Utviklere bruker særlig appspesifikke profiler, prosjektkommandoer, ferdige
tekstblokker og AI-status.

Kilder:

* [Elgato Stream Deck 6.6 – standardprofiler og festede handlinger](https://help.elgato.com/hc/en-us/articles/26005306818701-Elgato-Stream-Deck-6-6-Release-Notes)
* [Elgato Marketplace – produktivitet og utviklerverktøy](https://marketplace.elgato.com/stream-deck)
* [Elgatos ChatGPT & Codex-plugin](https://marketplace.elgato.com/product/chatgpt-codex-fb6a7052-2b1a-4500-ba2a-13996edf0b47)
* [Elgato Multi Actions](https://help.elgato.com/hc/en-us/articles/360027960912-Elgato-Stream-Deck-Multi-Actions)
* [Utviklerprofiler for Stream Deck](https://github.com/mikeckennedy/streamdeck-developer-profiles)
* [Brukernes produktivitetsoppsett](https://www.reddit.com/r/elgato/comments/1hhu8oj/are_stream_decks_good_for_work_productivity/)
* [Brukernes mest nyttige enkeltknapper](https://www.reddit.com/r/elgato/comments/1wh69jh/what_is_the_most_useful_stream_deck_button_you/)

Dette er omsatt til en ny **Daglig kontroll**-mal, 119 ferdige handlinger og et
fullt 18-knappers hovedoppsett. Hjem ligger fast i nederste høyre hjørne på alle
sider. Hovedsiden er en programstarter basert på installerte og festede apper:
Chrome, ChatGPT, ZCode, Claude, VS Code, GitHub Desktop, Terminal, Utforsker,
Discord, Obsidian, LM Studio, Steam og Xbox. Skjermbilde, system, flere apper og
lyd ligger i de fire siste plassene.

## Fordypning: nyttige knapper i reelle arbeidsoppsett

En ny gjennomgang 19. oktober tok med IT-, QA- og utvikleroppsett. Det tydeligste
mønsteret er at brukerne får mest verdi av handlinger som fjerner flere manuelle
steg: flytte et vindu til en annen skjerm, starte terminalkommandoer, åpne riktig
prosjektverktøy, styre møter og kjøre multihandlinger. Appspesifikke profiler
holder disse funksjonene tilgjengelige uten å fylle den globale forsiden.

* IT- og QA-brukere beskriver terminalkommandoer, VNC, ping, vindusflytting og
  profiler som følger aktiv app. [IT-tråd med konkrete arbeidsflyter](https://www.reddit.com/r/elgato/comments/1vgbu8v/stream_deck_usage_tips_for_someone_working_in_it/)
* Utvikleroppsett går igjen på formattering, lint, Git pull, GitHub Desktop,
  terminaler og egne globale/kontekstuelle sider. [Utvikler- og QA-profiler](https://www.reddit.com/r/streamdeckprofiles/comments/y1xger)
* Microsoft dokumenterer direkte Windows-snarveier for å flytte aktive vinduer
  mellom skjermer, virtuelle skrivebord, utklippshistorikk og festelayout.
  [Windows-snarveier](https://support.microsoft.com/en-au/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec)
* PowerToys tilfører OCR, fargevelger, alltid øverst, arbeidsområder og avansert
  innliming. [PowerToys](https://learn.microsoft.com/en-us/windows/powertoys/),
  [Advanced Paste](https://learn.microsoft.com/windows/powertoys/advanced-paste)
* Teams og Zoom har dokumenterte snarveier for mikrofon, kamera, deling, hånd,
  chat og avslutting. [Teams-snarveier](https://support.microsoft.com/en-us/accessibility/teams/keyboard-shortcuts-for-microsoft-teams),
  [Zoom-snarveier](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067050)
* GitHub Desktop har dokumenterte Windows-snarveier for endringer, historikk,
  grener, pull, push, terminal, editor og pull requests.
  [GitHub Desktop-snarveier](https://docs.github.com/en/desktop/overview/github-desktop-keyboard-shortcuts?platform=windows)

Dette er nå lagt inn som egne handlingsgrupper og komplette maler for PowerToys
og GitHub Desktop. Møtemalen er utvidet til alle 18 knapper. Standardforsiden er
fortsatt enkel; de nye handlingene velges fra biblioteket eller aktiveres som
egne profiler.

## Arbeidsflyten som bør være referansen

Elgatos oppstartsguide beskriver handlinger i høyrepanelet, knapperutenett
til venstre og konfigurasjon av den valgte knappen. Mapper opprettes ved å
dra Create Folder til en knapp; egne handlinger legges deretter i mappen.
Høyreklikk gir blant annet kopiering, sletting og flytting.
[Offisiell oppstartsguide](https://www.elgato.com/us/en/explorer/products/stream-deck/elgato-stream-deck-quick-start-guide/).

Agent Deck har handlingslisten til venstre og egenskaper til høyre. Dra/slipp
finnes, men dette er en egen layout. Det er ikke en nøyaktig gjengivelse av
Elgatos editor. Å legge en ny handling på en opptatt knapp legger automatisk
til et trinn i dagens implementasjon.

## Funksjoner og faktiske forskjeller

| Område | Elgato | Agent Deck nå |
|---|---|---|
| Visuell knappekonfigurasjon | Dra handlinger til knapper; rediger valgt handling | Finnes; mus/berøring, flytting/bytting, valg av ikon/farge/navn |
| Egendefinerte ikoner | Bilder fra fil, ikonbibliotek og animerte formater | 1 895 Lucide-ikoner og egne PNG-, JPEG-, GIF- og WebP-filer |
| Tekst på knapper | Skriftinnstillinger og plassering øverst/midt/nederst | Størrelse, plassering og fet skrift; vertsprotokollen begrenser etiketten til 24 UTF-8-byte |
| Profiler | Separate oppsett med Smart Profiles etter aktivt program | Finnes; regler basert på prosessnavn, manuell registrering i editoren |
| Mapper/sider | Egen mappehandling og sider; faste handlinger kan følge navigasjonen | Mapper med mappestakk, tilbakeknapp og festede knapper |
| Multihandlinger | Egen Multi Action-konfigurasjon med trinn og forsinkelser | Sekvensielle trinn og delay finnes; forenklet editor |
| Veksleknapper | Hotkey Switch og Multi Action Switch | Knapper med 2–8 tilstander |
| Dynamiske knapper | SDK kan oppdatere ikon, tittel og tilstand fra appen | Etikettvariabler og kortvarig suksess/feilfarge; ingen generell appstatusbinding |
| Trykk/slipp | SDK har separate tastened-/tasteopp-hendelser | Deck-handlingen utløses av klikk; generell hold/slipp-strøm mangler |
| Appintegrasjoner | Marketplace-plugins for blant annet OBS og Discord | Hurtigtaster, åpning, tekst, shell og HTTP; ingen tilsvarende pluginvert |
| Deling | Stream Deck-profiler og deling av handlinger | Eget JSON-format; ingen .streamDeckProfile-import |
| Programlivssyklus | Etablert skrivebordsapp | Lokalt Windows-program med WebView2, Python-vert og terminalprogram |

Kilder til funksjonene over:

* [Ikoner og støttede bildeformater](https://www.elgato.com/us/en/explorer/products/stream-deck/customize-stream-deck-with-icons-and-icon-packs/):
  egen fil, ikonbibliotek og Key Creator. Den generelle ikonguiden oppgir
  144×144; modellens oppstartsguide oppgir 72×72. Dette skal ikke behandles som
  én universell fysisk pikselstørrelse for alle modeller.
* [Titler og skriftinnstillinger](https://help.elgato.com/hc/en-us/articles/360027958532-Elgato-Stream-Deck-Custom-Titles-for-Actions).
* [Smart Profiles](https://www.elgato.com/uk/en/explorer/products/stream-deck/smart-profiles-stream-deck/):
  profil byttes etter programmet i forgrunnen.
* [Multi Actions](https://help.elgato.com/hc/en-us/articles/360027960912-Elgato-Stream-Deck-Multi-Actions):
  egen opprettelse fra handlingsliste/høyreklikk, ordnede trinn og forsinkelser.
* [Veksling mellom hurtigtaster](https://www.elgato.com/eu/hu/explorer/products/stream-deck/how-to-set-up-stream-deck-hotkeys/)
  og [Multi Action Switch i offisielle utgivelsesnotater](https://help.elgato.com/hc/de/articles/360028242631-Elgato-Stream-Deck-Software-Release-Notes).
* [Pinned Actions](https://www.elgato.com/us/en/explorer/products/stream-deck/pinned-actions-stream-deck/):
  samme plass gjennom sider og mapper innen én profil.
* [SDK: Keys](https://docs.elgato.com/streamdeck/sdk/guides/keys/):
  hendelser, dynamiske bilder/titler og tilstander.
* [Marketplace](https://marketplace.elgato.com/): plugin-, profil- og ikonøkosystemet.

## Kan vi bruke originalprogrammet direkte?

Det offisielle plugin-SDK-et er for utvidelser som kjører under Stream Deck-appen.
Elgato beskriver at appen eier kommunikasjonen med maskinvaren. Det er derfor
ikke dokumentasjon på at en ESP32-P4 med vår eksisterende serielle protokoll
kan registreres som en original Stream Deck ved å installere en vanlig plugin.
[Pluginmiljøet](https://docs.elgato.com/streamdeck/sdk/introduction/plugin-environment/).

Elgatos publiserte [HID-dokumentasjon](https://docs.elgato.com/streamdeck/hid/intro/)
beskriver kontroll av Stream Deck-maskinvare. [Stream Deck Module](https://www.elgato.com/us/en/p/stream-deck-module-6-keys)
er en fysisk Elgato-modul for innebygging i egne produkter. Ingen av disse
kildene bekrefter direkte støtte for den eksisterende ESP32-P4-løsningen.
Å emulere en enhet ville være et separat utviklings- og kompatibilitetsprosjekt,
ikke en verifisert snarvei. Ingen USB-identiteter eller fastvare ble endret
under denne researchen.

## Et eksisterende alternativ som bør prøves før egen pluginvert

[OpenDeck](https://github.com/nekename/OpenDeck/blob/main/README.md) er en
skrivebordsapp for Windows, macOS og Linux. Prosjektet oppgir støtte for mange
plugins laget for Stream Deck-SDK-et. Offisiell maskinvarestøtte er Elgato,
mens andre leverandører kan støttes av enhetsplugins.

Min vurdering: OpenDeck er en konkret kandidat for en avgrenset kompatibilitetstest
med en egen P4-bro. Det er ikke bekreftet at vår enhet virker. En slik bro må
overføre knappbilder og hendelser gjennom den eksisterende USB-eieren.
Pluginstøtte må testes per faktisk plugin; «mange» betyr ikke «alle».

## Valgt retning

Prosjektet er nå et rent Agent Deck. Den Elgato-lignende arbeidsflyten er bygd
inn i det lokale PC-programmet med dra og slipp, egne bilder, 1 895 ikoner,
multihandlinger, mapper, veksleknapper, profiler og bekreftet USB-status. En
eventuell kompatibilitetsbro for tredjepartsplugins er fortsatt et separat,
framtidig arbeid og er ikke nødvendig for vanlig bruk.
