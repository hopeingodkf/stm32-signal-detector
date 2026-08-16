#include "SignalDetector.hpp"

namespace
{

constexpr int32_t kSampleMax = 32760;

int32_t Abs32(int32_t value)
{
    return (value < 0) ? -value : value;
}

uint16_t ClampToSample(int32_t value)
{
    if (value < 0)
    {
        return 0U;
    }
    if (value > kSampleMax)
    {
        return static_cast<uint16_t>(kSampleMax);
    }
    return static_cast<uint16_t>(value);
}

}

SignalDetector::Config SignalDetector::DefaultConfig()
{
    Config config;
    config.level_ema_shift     = 3U;
    config.deviation_ema_shift = 3U;
    config.noise_ema_shift     = 7U;
    config.margin_on           = 2000U;
    config.margin_off          = 800U;
    config.deviation_limit     = 900U;
    config.confirm_samples     = 5U;
    config.hold_samples        = 50U;
    return config;
}

SignalDetector::SignalDetector()
    : SignalDetector(DefaultConfig())
{
}

SignalDetector::SignalDetector(const Config& config)
    : config_(config),
      level_accumulator_(0),
      deviation_accumulator_(0),
      noise_accumulator_(0),
      level_(0U),
      deviation_(0U),
      noise_floor_(0U),
      confirm_count_(0),
      hold_remaining_(0U),
      state_(State::Waiting)
{
}

void SignalDetector::Reset(uint16_t initial_level)
{
    level_accumulator_     = static_cast<int32_t>(initial_level) << config_.level_ema_shift;
    deviation_accumulator_ = 0;
    noise_accumulator_     = static_cast<int32_t>(initial_level) << config_.noise_ema_shift;

    level_          = initial_level;
    deviation_      = 0U;
    noise_floor_    = initial_level;
    confirm_count_  = 0;
    hold_remaining_ = 0U;
    state_          = State::Waiting;
}

void SignalDetector::UpdateFilters(uint16_t sample)
{
    const int32_t input = static_cast<int32_t>(sample);

    level_accumulator_ += input - (level_accumulator_ >> config_.level_ema_shift);
    level_ = ClampToSample(level_accumulator_ >> config_.level_ema_shift);

    const int32_t excursion = Abs32(input - static_cast<int32_t>(level_));

    deviation_accumulator_ += excursion - (deviation_accumulator_ >> config_.deviation_ema_shift);
    deviation_ = ClampToSample(deviation_accumulator_ >> config_.deviation_ema_shift);
}

uint16_t SignalDetector::ThresholdOn() const
{
    return ClampToSample(static_cast<int32_t>(noise_floor_) + static_cast<int32_t>(config_.margin_on));
}

uint16_t SignalDetector::ThresholdOff() const
{
    return ClampToSample(static_cast<int32_t>(noise_floor_) + static_cast<int32_t>(config_.margin_off));
}

bool SignalDetector::IsPresent() const
{
    return (level_ > ThresholdOn()) && (deviation_ < config_.deviation_limit);
}

SignalDetector::State SignalDetector::Update(uint16_t sample)
{
    UpdateFilters(sample);

    switch (state_)
    {
    case State::Waiting:
        noise_accumulator_ += static_cast<int32_t>(level_) - (noise_accumulator_ >> config_.noise_ema_shift);
        noise_floor_ = ClampToSample(noise_accumulator_ >> config_.noise_ema_shift);

        if (IsPresent())
        {
            confirm_count_ = 1;
            state_         = State::Confirming;
        }
        break;

    case State::Confirming:
        if (IsPresent())
        {
            ++confirm_count_;
            if (confirm_count_ >= static_cast<int16_t>(config_.confirm_samples))
            {
                state_ = State::Active;
            }
        }
        else
        {
            --confirm_count_;
            if (confirm_count_ <= 0)
            {
                confirm_count_ = 0;
                state_         = State::Waiting;
            }
        }
        break;

    case State::Active:
        if (level_ < ThresholdOff())
        {
            hold_remaining_ = config_.hold_samples;
            state_          = State::Holding;
        }
        break;

    case State::Holding:
        if (level_ > ThresholdOn())
        {
            hold_remaining_ = 0U;
            state_          = State::Active;
        }
        else
        {
            --hold_remaining_;
            if (hold_remaining_ == 0U)
            {
                confirm_count_ = 0;
                state_         = State::Waiting;
            }
        }
        break;

    default:
        state_ = State::Waiting;
        break;
    }

    return state_;
}

SignalDetector::Snapshot SignalDetector::GetSnapshot() const
{
    Snapshot snapshot;
    snapshot.level          = level_;
    snapshot.deviation      = deviation_;
    snapshot.noise_floor    = noise_floor_;
    snapshot.threshold_on   = ThresholdOn();
    snapshot.threshold_off  = ThresholdOff();
    snapshot.hold_remaining = hold_remaining_;
    snapshot.confirm_count  = static_cast<uint8_t>(confirm_count_);
    snapshot.state          = state_;
    return snapshot;
}
