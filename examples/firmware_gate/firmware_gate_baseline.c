// SPDX-License-Identifier: Apache-2.0

#include <stdint.h>

#include "simple_system_common.h"

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  pcount_enable(0);
  pcount_reset();
  pcount_enable(1);

  uint32_t sum = 0;
  for (uint32_t index = 0; index < 256; ++index) {
    asm volatile("addi %0, %0, 1" : "+r"(sum));
  }

  pcount_enable(0);

  puts("Firmware gate result\n");
  puthex(sum);
  putchar('\n');

  return sum == 256 ? 0 : 1;
}
