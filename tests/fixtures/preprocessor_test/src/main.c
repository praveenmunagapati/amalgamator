#include <stdio.h>

#ifdef HAL_STM32
#include "stm32.h"
#endif

#ifdef HAL_AVR
#include "avr.h"
#endif

int main() {
#ifdef HAL_STM32
    printf("STM32 Init: %d\n", stm32_init());
#endif

#ifdef HAL_AVR
    printf("AVR Init: %d\n", avr_init());
#endif
    return 0;
}
