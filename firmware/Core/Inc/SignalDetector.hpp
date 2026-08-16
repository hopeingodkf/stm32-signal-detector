#ifndef SIGNAL_DETECTOR_HPP
#define SIGNAL_DETECTOR_HPP

#include <cstdint>

class SignalDetector
{
public:
    enum class State : uint8_t
    {
        Waiting    = 0,
        Confirming = 1,
        Active     = 2,
        Holding    = 3
    };

    struct Config
    {
        uint8_t  level_ema_shift;
        uint8_t  deviation_ema_shift;
        uint8_t  noise_ema_shift;
        uint16_t margin_on;
        uint16_t margin_off;
        uint16_t deviation_limit;
        uint8_t  confirm_samples;
        uint16_t hold_samples;
    };

    struct Snapshot
    {
        uint16_t level;
        uint16_t deviation;
        uint16_t noise_floor;
        uint16_t threshold_on;
        uint16_t threshold_off;
        uint16_t hold_remaining;
        uint8_t  confirm_count;
        State    state;
    };

    static Config DefaultConfig();

    SignalDetector();
    explicit SignalDetector(const Config& config);

    void  Reset(uint16_t initial_level);
    State Update(uint16_t sample);

    State GetState() const { return state_; }
    bool  IsActive() const { return state_ == State::Active || state_ == State::Holding; }

    Snapshot GetSnapshot() const;

private:
    void UpdateFilters(uint16_t sample);

    uint16_t ThresholdOn() const;
    uint16_t ThresholdOff() const;
    bool     IsPresent() const;

    Config   config_;
    int32_t  level_accumulator_;
    int32_t  deviation_accumulator_;
    int32_t  noise_accumulator_;
    uint16_t level_;
    uint16_t deviation_;
    uint16_t noise_floor_;
    int16_t  confirm_count_;
    uint16_t hold_remaining_;
    State    state_;
};

#endif
