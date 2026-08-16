#include "detector_app.h"

#include "main.h"
#include "adc.h"
#include "fmac.h"
#include "tim.h"
#include "usart.h"
#include "gpio.h"
#include "cmsis_os.h"

#include "SignalDetector.hpp"

#include <cstring>

extern "C"
{
extern DMA_HandleTypeDef hdma_fmac_write;
extern DMA_HandleTypeDef hdma_fmac_read;
}

namespace
{

constexpr uint16_t kFirTaps       = 100U;
constexpr uint16_t kBlockSamples  = 100U;
constexpr uint16_t kBufferSamples = kBlockSamples * 2U;
constexpr int16_t  kFirCoefficient = 327;

constexpr uint32_t kX2Base = 0U;
constexpr uint32_t kX2Size = 100U;
constexpr uint32_t kX1Base = 100U;
constexpr uint32_t kX1Size = 110U;
constexpr uint32_t kYBase  = 210U;
constexpr uint32_t kYSize  = 46U;

constexpr uint32_t kBlockReadyFlag = 0x01U;

constexpr uint16_t kPacketMagic = 0xA5C3U;

constexpr uint32_t kTelemetryQueueDepth = 8U;

struct TelemetryPacket
{
    uint16_t magic;
    uint16_t raw;
    uint16_t filtered;
    uint16_t level;
    uint16_t deviation;
    uint16_t noise_floor;
    uint16_t threshold_on;
    uint16_t threshold_off;
    uint16_t hold_remaining;
    uint16_t fmac_status;
    uint16_t adc_errors;
    uint8_t  state;
    uint8_t  confirm_count;
    uint16_t checksum;
};

static_assert(sizeof(TelemetryPacket) == 26U, "telemetry packet layout must match tools/telemetry.py");

int16_t          g_adc_raw[kBufferSamples];
int16_t          g_fmac_output[kBufferSamples];

SignalDetector   g_detector;

osMessageQueueId_t g_telemetry_queue = nullptr;
osThreadId_t       g_detector_thread = nullptr;

volatile uint16_t g_ready_block  = 0U;
volatile uint16_t g_adc_errors   = 0U;

TelemetryPacket  g_transmit_packet;

void FmacWaitStartCleared()
{
    while ((FMAC->PARAM & FMAC_PARAM_START) != 0U)
    {
    }
}

void FmacPrepareWriteChannel()
{
    HAL_DMA_Abort(&hdma_fmac_write);
    hdma_fmac_write.Init.Mode = DMA_NORMAL;
    HAL_DMA_Init(&hdma_fmac_write);
}

void FmacConfigure()
{
    FMAC->CR = FMAC_CR_RESET;
    while ((FMAC->CR & FMAC_CR_RESET) != 0U)
    {
    }

    FMAC->X1BUFCFG = (kX1Base << FMAC_X1BUFCFG_X1_BASE_Pos)
                   | (kX1Size << FMAC_X1BUFCFG_X1_BUF_SIZE_Pos);

    FMAC->X2BUFCFG = (kX2Base << FMAC_X2BUFCFG_X2_BASE_Pos)
                   | (kX2Size << FMAC_X2BUFCFG_X2_BUF_SIZE_Pos);

    FMAC->YBUFCFG = (kYBase << FMAC_YBUFCFG_Y_BASE_Pos)
                  | (kYSize << FMAC_YBUFCFG_Y_BUF_SIZE_Pos);

    FMAC->PARAM = (static_cast<uint32_t>(kFirTaps) << FMAC_PARAM_P_Pos)
                | FMAC_FUNC_LOAD_X2
                | FMAC_PARAM_START;

    for (uint16_t i = 0U; i < kFirTaps; ++i)
    {
        FMAC->WDATA = static_cast<uint32_t>(static_cast<uint16_t>(kFirCoefficient));
    }
    FmacWaitStartCleared();

    FMAC->PARAM = (static_cast<uint32_t>(kFirTaps) << FMAC_PARAM_P_Pos)
                | FMAC_FUNC_LOAD_X1
                | FMAC_PARAM_START;

    for (uint16_t i = 0U; i < kFirTaps; ++i)
    {
        FMAC->WDATA = 0U;
    }
    FmacWaitStartCleared();
}

void FmacStartStreaming()
{
    HAL_DMA_Start(&hdma_fmac_read,
                  reinterpret_cast<uint32_t>(&FMAC->RDATA),
                  reinterpret_cast<uint32_t>(g_fmac_output),
                  kBufferSamples);

    FMAC->CR = FMAC_CR_DMAREN | FMAC_CR_DMAWEN | FMAC_CR_CLIPEN;

    FMAC->PARAM = (static_cast<uint32_t>(kFirTaps) << FMAC_PARAM_P_Pos)
                | FMAC_FUNC_CONVO_FIR
                | FMAC_PARAM_START;
}

void FmacSubmitBlock(uint16_t block)
{
    HAL_DMA_Start_IT(&hdma_fmac_write,
                     reinterpret_cast<uint32_t>(&g_adc_raw[block * kBlockSamples]),
                     reinterpret_cast<uint32_t>(&FMAC->WDATA),
                     kBlockSamples);
}

void OnBlockReady(uint16_t block)
{
    g_ready_block = block;
    FmacSubmitBlock(block);

    if (g_detector_thread != nullptr)
    {
        osThreadFlagsSet(g_detector_thread, kBlockReadyFlag);
    }
}

uint16_t ComputeChecksum(const TelemetryPacket& packet)
{
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&packet);
    const size_t   count = sizeof(TelemetryPacket) - sizeof(uint16_t);

    uint16_t sum = 0U;
    for (size_t i = 0U; i < count; ++i)
    {
        sum = static_cast<uint16_t>(sum + bytes[i]);
    }
    return sum;
}

uint16_t ToUnsigned(int16_t value)
{
    return (value < 0) ? 0U : static_cast<uint16_t>(value);
}

}

extern "C" void DetectorApp_CreateQueues(void)
{
    g_telemetry_queue = osMessageQueueNew(kTelemetryQueueDepth, sizeof(TelemetryPacket), nullptr);
}

extern "C" void DetectorApp_Init(void)
{
    std::memset(g_adc_raw, 0, sizeof(g_adc_raw));
    std::memset(g_fmac_output, 0, sizeof(g_fmac_output));

    FmacPrepareWriteChannel();
    FmacConfigure();
    FmacStartStreaming();

    HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED);
    HAL_ADC_Start_DMA(&hadc1, reinterpret_cast<uint32_t*>(g_adc_raw), kBufferSamples);
    HAL_TIM_Base_Start(&htim3);
}

extern "C" void DetectorApp_DetectorTask(void *argument)
{
    (void)argument;

    g_detector_thread = osThreadGetId();
    g_detector.Reset(0U);

    DetectorApp_Init();

    for (;;)
    {
        osThreadFlagsWait(kBlockReadyFlag, osFlagsWaitAny, osWaitForever);

        const uint16_t settled_block = g_ready_block ^ 1U;
        const uint16_t index         = static_cast<uint16_t>(settled_block * kBlockSamples + (kBlockSamples - 1U));

        const uint16_t filtered = ToUnsigned(g_fmac_output[index]);
        const uint16_t raw      = ToUnsigned(g_adc_raw[index]);

        g_detector.Update(filtered);

        HAL_GPIO_WritePin(LED_ACTIVE_GPIO_Port,
                          LED_ACTIVE_Pin,
                          g_detector.IsActive() ? GPIO_PIN_SET : GPIO_PIN_RESET);

        const SignalDetector::Snapshot snapshot = g_detector.GetSnapshot();

        TelemetryPacket packet;
        packet.magic          = kPacketMagic;
        packet.raw            = raw;
        packet.filtered       = filtered;
        packet.level          = snapshot.level;
        packet.deviation      = snapshot.deviation;
        packet.noise_floor    = snapshot.noise_floor;
        packet.threshold_on   = snapshot.threshold_on;
        packet.threshold_off  = snapshot.threshold_off;
        packet.hold_remaining = snapshot.hold_remaining;
        packet.fmac_status    = static_cast<uint16_t>(FMAC->SR & (FMAC_SR_OVFL | FMAC_SR_UNFL | FMAC_SR_SAT));
        packet.adc_errors     = g_adc_errors;
        packet.state          = static_cast<uint8_t>(snapshot.state);
        packet.confirm_count  = snapshot.confirm_count;
        packet.checksum       = ComputeChecksum(packet);

        if (g_telemetry_queue != nullptr)
        {
            osMessageQueuePut(g_telemetry_queue, &packet, 0U, 0U);
        }
    }
}

extern "C" void DetectorApp_TelemetryTask(void *argument)
{
    (void)argument;

    TelemetryPacket packet;

    for (;;)
    {
        if (g_telemetry_queue == nullptr)
        {
            osDelay(10U);
            continue;
        }

        if (osMessageQueueGet(g_telemetry_queue, &packet, nullptr, osWaitForever) != osOK)
        {
            continue;
        }

        while (hlpuart1.gState != HAL_UART_STATE_READY)
        {
            osDelay(1U);
        }

        g_transmit_packet = packet;

        HAL_UART_Transmit_DMA(&hlpuart1,
                              reinterpret_cast<uint8_t*>(&g_transmit_packet),
                              sizeof(g_transmit_packet));
    }
}

extern "C" void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1)
    {
        OnBlockReady(0U);
    }
}

extern "C" void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1)
    {
        OnBlockReady(1U);
    }
}

extern "C" void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1)
    {
        ++g_adc_errors;
    }
}
