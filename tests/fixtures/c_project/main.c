#include <stdio.h>
#include "utils.h"

int main() {
    int a = 5, b = 3;
    printf("Add: %d + %d = %d\n", a, b, add(a, b));
    printf("Multiply: %d * %d = %d\n", a, b, multiply(a, b));
    printf("Amalgamator works!\n");
    return 0;
}
