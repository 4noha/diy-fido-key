# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.28.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(diy_fido_ble)
set(U8G2_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../vendor/u8g2)
file(GLOB U8G2_SOURCES ${U8G2_ROOT}/csrc/*.c)
target_sources(app PRIVATE src/main.c src/oled.c src/user_presence.c src/key_import.c ${U8G2_SOURCES})
target_include_directories(app PRIVATE ${U8G2_ROOT}/csrc src)
