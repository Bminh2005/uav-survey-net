CC ?= gcc
CFLAGS ?= -Wall -Wextra -O2 -Iinclude -pthread
LDFLAGS ?= -pthread -lm

SRC_DIR = src
INC_DIR = include
OBJ_DIR = build
BIN_DIR = bin
TARGET  = $(BIN_DIR)/uav_server

SRCS = $(wildcard $(SRC_DIR)/*.c)
OBJS = $(patsubst $(SRC_DIR)/%.c, $(OBJ_DIR)/%.o, $(SRCS))

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJS) | $(BIN_DIR)
	@echo "Linking $@..."
	$(CC) $(OBJS) -o $@ $(LDFLAGS)
	@echo "================================================="
	@echo " Biên dịch thành công: $@"
	@echo " Khởi chạy bằng lệnh: ./bin/uav_server"
	@echo "================================================="

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c | $(OBJ_DIR)
	@echo "Compiling $<..."
	$(CC) $(CFLAGS) -c $< -o $@

$(OBJ_DIR):
	mkdir -p $(OBJ_DIR)

$(BIN_DIR):
	mkdir -p $(BIN_DIR)

run: $(TARGET)
	./$(TARGET) 8080

clean:
	rm -rf $(OBJ_DIR) $(BIN_DIR)
	@echo "Đã dọn dẹp thư mục build."

