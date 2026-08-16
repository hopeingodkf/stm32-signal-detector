TARGET = signal

TOOLCHAIN ?= C:/ST/STM32CubeIDE_2.2.0/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740/tools/bin
PROGRAMMER ?= C:/ST/STM32CubeIDE_2.2.0/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_2.2.500.202603051304/tools/bin/STM32_Programmer_CLI.exe

CC  = $(TOOLCHAIN)/arm-none-eabi-gcc
CXX = $(TOOLCHAIN)/arm-none-eabi-g++
CP  = $(TOOLCHAIN)/arm-none-eabi-objcopy
SZ  = $(TOOLCHAIN)/arm-none-eabi-size

BUILD_DIR = build

FREERTOS = Middlewares/Third_Party/FreeRTOS/Source
HAL      = Drivers/STM32G4xx_HAL_Driver/Src

C_SOURCES = \
  $(wildcard Core/Src/*.c) \
  $(wildcard $(HAL)/*.c) \
  $(wildcard $(FREERTOS)/*.c) \
  $(FREERTOS)/CMSIS_RTOS_V2/cmsis_os2.c \
  $(FREERTOS)/portable/GCC/ARM_CM4F/port.c \
  $(FREERTOS)/portable/MemMang/heap_4.c

CXX_SOURCES = $(wildcard Core/Src/*.cpp)

ASM_SOURCES = Core/Startup/startup_stm32g474retx.s

C_INCLUDES = \
  -ICore/Inc \
  -IDrivers/STM32G4xx_HAL_Driver/Inc \
  -IDrivers/STM32G4xx_HAL_Driver/Inc/Legacy \
  -IDrivers/CMSIS/Device/ST/STM32G4xx/Include \
  -IDrivers/CMSIS/Include \
  -I$(FREERTOS)/include \
  -I$(FREERTOS)/CMSIS_RTOS_V2 \
  -I$(FREERTOS)/portable/GCC/ARM_CM4F

C_DEFS = -DUSE_HAL_DRIVER -DSTM32G474xx

MCU = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard

OPT = -Og -g3

COMMON_FLAGS = $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -Wextra \
               -ffunction-sections -fdata-sections -fstack-usage

CFLAGS   = $(COMMON_FLAGS) -std=gnu11
CXXFLAGS = $(COMMON_FLAGS) -std=gnu++17 -fno-exceptions -fno-rtti -fno-threadsafe-statics

LDSCRIPT = STM32G474RETX_FLASH.ld
LDFLAGS  = $(MCU) -T$(LDSCRIPT) -specs=nano.specs -specs=nosys.specs \
           -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections \
           -Wl,--print-memory-usage

OBJECTS  = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(CXX_SOURCES:.cpp=.o)))
OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))

vpath %.c $(sort $(dir $(C_SOURCES)))
vpath %.cpp $(sort $(dir $(CXX_SOURCES)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).bin

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -MMD -MP $< -o $@

$(BUILD_DIR)/%.o: %.cpp | $(BUILD_DIR)
	$(CXX) -c $(CXXFLAGS) -MMD -MP $< -o $@

$(BUILD_DIR)/%.o: %.s | $(BUILD_DIR)
	$(CC) -c $(MCU) -x assembler-with-cpp $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS)
	$(CXX) $(OBJECTS) $(LDFLAGS) -o $@
	$(SZ) $@

$(BUILD_DIR)/$(TARGET).bin: $(BUILD_DIR)/$(TARGET).elf
	$(CP) -O binary -S $< $@

$(BUILD_DIR):
	mkdir -p $@

erase:
	"$(PROGRAMMER)" -c port=SWD -e all

flash: $(BUILD_DIR)/$(TARGET).elf
	"$(PROGRAMMER)" -c port=SWD -w $< -v -rst

clean:
	rm -rf $(BUILD_DIR)

-include $(wildcard $(BUILD_DIR)/*.d)

.PHONY: all clean erase flash
