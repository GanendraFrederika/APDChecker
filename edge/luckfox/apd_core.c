#include "apd_core.h"
#include <math.h>
#include <string.h>

static bool valid_box(apd_box b) {
    return isfinite(b.x1) && isfinite(b.y1) && isfinite(b.x2) &&
           isfinite(b.y2) && isfinite(b.confidence) &&
           b.x2 > b.x1 && b.y2 > b.y1 &&
           b.confidence >= 0.0f && b.confidence <= 1.0f;
}

bool apd_assess(const apd_box *people, size_t n,
                const apd_equipment *equipment, size_t m,
                uint8_t required, float threshold, apd_assessment *out) {
    if (!out) return false;
    memset(out, 0, sizeof(*out));
    out->observation = APD_MODEL_ERROR;
    if ((!people && n) || (!equipment && m) ||
        n > APD_MAX_PEOPLE || m > APD_MAX_EQUIPMENT ||
        !required || (required & ~APD_ALL_PPE) ||
        !isfinite(threshold) || threshold < 0.0f || threshold > 1.0f) return false;
    for (size_t i = 0; i < n; ++i) {
        if (!valid_box(people[i])) { ++out->invalid; continue; }
        if (people[i].confidence < threshold) continue;
        out->people[out->people_count++].box = people[i];
    }
    for (size_t j = 0; j < m; ++j) {
        apd_equipment gear = equipment[j];
        if (!valid_box(gear.box)) { ++out->invalid; continue; }
        if (gear.box.confidence < threshold) continue;
        if (!gear.kind || (gear.kind & (gear.kind - 1u)) ||
            (gear.kind & ~APD_ALL_PPE)) { ++out->invalid; continue; }
        if (!(gear.kind & required)) continue;
        float cx = (gear.box.x1 + gear.box.x2) / 2.0f;
        float cy = (gear.box.y1 + gear.box.y2) / 2.0f;
        size_t candidate = 0, count = 0;
        for (size_t i = 0; i < out->people_count; ++i) {
            apd_box person = out->people[i].box;
            if (!(person.x1 <= cx && cx <= person.x2 &&
                  person.y1 <= cy && cy <= person.y2)) continue;
            float ry = (cy - person.y1) / (person.y2 - person.y1);
            if ((gear.kind & (APD_HELMET | APD_MASK | APD_GOGGLES)) && ry > 0.55f) continue;
            if (gear.kind == APD_SHOES && ry < 0.5f) continue;
            candidate = i; ++count;
        }
        if (count != 1) { ++out->unassigned; continue; }
        if (gear.negative) out->people[candidate].negative |= gear.kind;
        else out->people[candidate].positive |= gear.kind;
    }
    bool uncertain = out->unassigned || out->invalid;
    for (size_t i = 0; i < out->people_count; ++i) {
        apd_person_result *person = &out->people[i];
        person->conflicts = person->positive & person->negative;
        uint8_t negative = person->negative & ~person->conflicts;
        uint8_t positive = person->positive & ~person->conflicts;
        if (negative & required) {
            person->state = APD_VIOLATION; ++out->violators;
        } else if ((positive & required) == required) {
            person->state = APD_COMPLIANT;
        } else {
            person->state = APD_UNKNOWN; uncertain = true;
        }
    }
    out->observation = out->violators ? APD_VIOLATION : uncertain ? APD_UNKNOWN :
                       out->people_count ? APD_COMPLIANT : APD_NO_PERSON;
    return true;
}

bool apd_debouncer_init(apd_debouncer *s, apd_timing t) {
    if (!s) return false;
    memset(s, 0, sizeof(*s));
    s->candidate = -1;
    if (!t.min_samples || !t.max_gap_ms || t.violation_ms > INT32_MAX ||
        t.clear_ms > INT32_MAX || t.max_gap_ms > INT32_MAX) return false;
    s->timing = t;
    return true;
}

void apd_debouncer_fault(apd_debouncer *s) {
    if (!s) return;
    s->alarm_indication = false;
    s->candidate = -1;
    s->samples = 0;
}

bool apd_debouncer_update(apd_debouncer *s, apd_observation observation, uint32_t now) {
    if (!s) return false;
    if (observation < APD_UNKNOWN || observation > APD_STARTING ||
        !s->timing.min_samples || !s->timing.max_gap_ms) {
        apd_debouncer_fault(s); return false;
    }
    if (s->has_previous) {
        uint32_t gap = now - s->previous_ms;
        /* Unsigned subtraction handles clock wrap. Equal/backward timestamps
         * are rejected so replaying a cached frame cannot add a sample. */
        if (!gap || gap > INT32_MAX) { apd_debouncer_fault(s); return false; }
        if (gap > s->timing.max_gap_ms) { s->candidate = -1; s->samples = 0; }
    }
    s->has_previous = true;
    s->previous_ms = now;
    if (observation == APD_CAMERA_LOST || observation == APD_MODEL_ERROR ||
        observation == APD_STARTING) { apd_debouncer_fault(s); return true; }
    int8_t target = observation == APD_VIOLATION ? 1 :
                    (observation == APD_COMPLIANT || observation == APD_NO_PERSON) ? 0 : -1;
    if (target < 0) { s->candidate = -1; s->samples = 0; return true; }
    if (s->candidate != target) {
        s->candidate = target; s->since_ms = now; s->samples = 1;
    } else if (s->samples < UINT16_MAX) { ++s->samples; }
    uint32_t delay = target ? s->timing.violation_ms : s->timing.clear_ms;
    if (s->samples >= s->timing.min_samples && now - s->since_ms >= delay)
        s->alarm_indication = target != 0;
    return true;
}

uint8_t apd_crc8(const uint8_t *data, size_t size) {
    uint8_t crc = 0;
    if (!data) return crc;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (uint8_t)((crc << 1) ^ ((crc & 0x80u) ? 0x07u : 0u));
    }
    return crc;
}

const char *apd_observation_name(apd_observation o) {
    switch (o) {
        case APD_UNKNOWN: return "UNKNOWN";
        case APD_COMPLIANT: return "COMPLIANT";
        case APD_VIOLATION: return "VIOLATION";
        case APD_NO_PERSON: return "NO_PERSON";
        case APD_CAMERA_LOST: return "CAMERA_LOST";
        case APD_MODEL_ERROR: return "MODEL_ERROR";
        case APD_STARTING: return "STARTING";
        default: return "MODEL_ERROR";
    }
}
