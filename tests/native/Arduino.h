#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
uint32_t millis();
struct ConsoleLog {template<class... T> int printf(const char* f,T... v){return std::printf(f,v...);}};
inline ConsoleLog Serial;
