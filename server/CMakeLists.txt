cmake_minimum_required(VERSION 3.10)
project(uav_server C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -O2 -pthread")

find_package(Threads REQUIRED)

include_directories(include)

file(GLOB SOURCES "src/*.c")

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/bin)

add_executable(uav_server ${SOURCES})

target_link_libraries(uav_server
    Threads::Threads
    m
)

