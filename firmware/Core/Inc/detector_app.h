#ifndef DETECTOR_APP_H
#define DETECTOR_APP_H

#ifdef __cplusplus
extern "C" {
#endif

void DetectorApp_Init(void);
void DetectorApp_CreateQueues(void);
void DetectorApp_DetectorTask(void *argument);
void DetectorApp_TelemetryTask(void *argument);

#ifdef __cplusplus
}
#endif

#endif
