# Lokal verifikasjon

Agent Deck er nå et rent Deck-produkt. Fastvaren inneholder én fullskjerms
6 × 3-flate, og Windows-terminalen er hovedprogrammet. Den lokale grafiske
editoren åpnes fra terminalen med F8.

Verifikasjonen dekker:

- validering, lagring og redigering av profiler og tomme sider
- mapper og tilbake-navigasjon
- festede knapper og tilstandsknapper
- flere handlinger, hurtigtaster og beskyttelse mot rekursjon
- 1 895 innebygde Lucide-ikoner
- import og normalisering av egne bilder
- native LVGL-rendering i 1024 × 600
- ESP-IDF 6.1-bygg
- COM4-protokoll, 21 syntetiske knappetrykk og stabil boot-ID
- eksplisitt LCD-baklys ved oppstart og gjenoppretting over USB

Maskinvaretesten sender ingen hurtigtaster, shell-kommandoer eller andre
handlinger til Windows. COM6 berøres ikke. Detaljerte logger og skjermbilder
lagres lokalt under `build/`.
