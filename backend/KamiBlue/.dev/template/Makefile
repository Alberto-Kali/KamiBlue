CFLAGS = -g -O2 -Wall -D_XUTILS_DEBUG -D_ASSERT_XLOG
LIBS = -lpthread -lm
LD_LIBS = ./lib/xutils/libxutils.a
COMPAT_SRC = ./lib/xutils/compat_isoc23.c
COMPAT_OBJ = ./lib/xutils/compat_isoc23.o

ifeq ($(XUTILS_USE_SSL),y)
CFLAGS += -D_XUTILS_USE_SSL
LIBS += -lssl -lcrypto
endif

CFLAGS += -I./lib/xutils

# Directories
SRC_DIR = src
BIN_DIR = ./

# Find all .c files in src and generate corresponding executable names
SRCS = $(wildcard $(SRC_DIR)/*.c)
EXECS = $(addprefix $(BIN_DIR), $(notdir $(basename $(SRCS))))

all: $(EXECS)

$(COMPAT_OBJ): $(COMPAT_SRC)
	$(CC) $(CFLAGS) -c -o $@ $<

# Generic rule: build any executable in BIN_DIR from its .c file in SRC_DIR
$(BIN_DIR)%: $(SRC_DIR)/%.c $(COMPAT_OBJ)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $< $(COMPAT_OBJ) $(LD_LIBS) $(LIBS)

.PHONY: clean
clean:
	$(RM) $(EXECS) $(COMPAT_OBJ)
