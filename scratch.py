from amalgamator.languages.preprocessor import CPreprocessor

pp = CPreprocessor(['HAL_STM32'])
code = '''#include <stdio.h>
#ifdef HAL_STM32
#include "stm32.h"
#endif
'''

for line in code.splitlines(keepends=True):
    print(pp.process_line(line), repr(line))
