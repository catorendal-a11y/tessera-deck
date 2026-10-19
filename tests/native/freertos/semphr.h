#pragma once
typedef int SemaphoreHandle_t;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void){return 1;}
static inline void xSemaphoreTake(SemaphoreHandle_t unused,int timeout){(void)unused;(void)timeout;}
static inline void xSemaphoreGive(SemaphoreHandle_t unused){(void)unused;}
