#pragma once
/* The cockpit palette, shared with the native test that checks text contrast (WCAG AA, 4.5:1 for body text). */
#include <stdint.h>

namespace ui_palette {
constexpr uint32_t Bg=0x0A0E10,RailBg=0x0F1518,Card=0x12191D,RailOn=0x18232A,Line=0x3A4950,WarnBg=0x2B2314;
constexpr uint32_t Text=0xEAF2EF,Soft=0xC4D0D4,Muted=0x8D9AA0,Dim=0x8FA0A8;
constexpr uint32_t Accent=0x58E09B,Cyan=0x4DD0E1,Purple=0xB388FF,Amber=0xFFB74D,Red=0xFF7070;
constexpr uint32_t PressedBg=0x254E3B,OkBg=0x1E6042,AlertBg=0x6E2633;
}
