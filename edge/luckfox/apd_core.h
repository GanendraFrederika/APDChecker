/* Portable C99 policy core for future RV1103 integration.
 * NO camera/RKNN/serial driver. No heap allocation. Not a deployed detector.
 */
#ifndef APD_CORE_H
#define APD_CORE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define APD_MAX_PEOPLE 8
#define APD_MAX_EQUIPMENT 64
#define APD_GLOVE  (1u << 0)
#define APD_GOGGLES (1u << 1)
#define APD_HELMET (1u << 2)
#define APD_MASK   (1u << 3)
#define APD_SHOES  (1u << 4)
#define APD_VEST   (1u << 5)
#define APD_ALL_PPE ((1u << 6) - 1u)

typedef enum {
    APD_UNKNOWN, APD_COMPLIANT, APD_VIOLATION, APD_NO_PERSON,
    APD_CAMERA_LOST, APD_MODEL_ERROR, APD_STARTING
} apd_observation;

typedef struct { float x1, y1, x2, y2, confidence; } apd_box;
typedef struct { apd_box box; uint8_t kind; bool negative; } apd_equipment;
typedef struct {
    apd_box box;
    uint8_t positive, negative, conflicts;
    apd_observation state;
} apd_person_result;
typedef struct {
    apd_observation observation;
    size_t people_count, violators, unassigned, invalid;
    apd_person_result people[APD_MAX_PEOPLE];
} apd_assessment;
typedef struct {
    uint32_t violation_ms, clear_ms, max_gap_ms;
    uint16_t min_samples;
} apd_timing;
typedef struct {
    apd_timing timing;
    uint32_t previous_ms, since_ms;
    uint16_t samples;
    bool alarm_indication, has_previous;
    int8_t candidate; /* -1 unknown, 0 clear, 1 violation */
} apd_debouncer;

bool apd_assess(const apd_box *people, size_t people_count,
                const apd_equipment *equipment, size_t equipment_count,
                uint8_t required, float min_confidence, apd_assessment *out);
bool apd_debouncer_init(apd_debouncer *state, apd_timing timing);
bool apd_debouncer_update(apd_debouncer *state, apd_observation observation,
                          uint32_t monotonic_ms);
void apd_debouncer_fault(apd_debouncer *state);
uint8_t apd_crc8(const uint8_t *data, size_t size);
const char *apd_observation_name(apd_observation observation);
#endif
