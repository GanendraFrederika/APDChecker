/* APD3 candidate: NOT uploaded/commissioned. Old v1.9 preserved separately.
 * No Servo, RTC or power gating. Pin plan and display policy require verification.
 * Both commissioning gates default OFF. No auto serial commands at boot.
 */
extern "C" {
#include "receiver_core.h"
}
#include <avr/wdt.h>
#ifndef APD_INDICATORS_COMMISSIONED
#define APD_INDICATORS_COMMISSIONED 0
#endif
#ifndef APD_ALARM_COMMISSIONED
#define APD_ALARM_COMMISSIONED 0
#endif
#ifndef APD_RELAY_ACTIVE_HIGH
#define APD_RELAY_ACTIVE_HIGH 1
#endif
#ifndef APD_WATCHDOG_BOOTLOADER_VERIFIED
#define APD_WATCHDOG_BOOTLOADER_VERIFIED 0
#endif
#if APD_ALARM_COMMISSIONED && !APD_WATCHDOG_BOOTLOADER_VERIFIED
#error "Alarm requires verified Uno bootloader/watchdog behavior"
#endif
#if APD_ALARM_COMMISSIONED && !APD_INDICATORS_COMMISSIONED
#error "Commission indicators/site policy before alarm"
#endif
static const uint8_t INDICATORS[3]={4,5,6}; /* vest green, shoes yellow, helmet red */
static const uint8_t FAULT_LED=13, RELAY=10, AUDIO=9;
/* Disable a watchdog left active after reset before static constructors/setup.
 * This cannot repair an incompatible bootloader; commissioning gate stays OFF. */
static uint8_t resetCause __attribute__((section(".noinit")));
static void earlyWatchdogDisable(void) __attribute__((naked, section(".init3"), used));
static void earlyWatchdogDisable(void) {resetCause=MCUSR; MCUSR=0; wdt_disable();}
static mcu_receiver receiver;
static char reply[MCU_LINE_BYTES];
void setup() {
    /* Reset reason cleared before enabling watchdog; verify bootloader behavior. */
    MCUSR=0; wdt_disable();
    for(uint8_t i=0;i<3;++i) {digitalWrite(INDICATORS[i],LOW); pinMode(INDICATORS[i],OUTPUT);}
    pinMode(FAULT_LED,OUTPUT);
#if APD_ALARM_COMMISSIONED
    digitalWrite(RELAY,APD_RELAY_ACTIVE_HIGH?LOW:HIGH); pinMode(RELAY,OUTPUT);
    digitalWrite(AUDIO,LOW); pinMode(AUDIO,OUTPUT);
#else
    /* Unknown relay polarity: don't drive it. Disconnect relay while developing;
     * a floating input is NOT guaranteed OFF without the right external pull. */
    pinMode(RELAY,INPUT); digitalWrite(RELAY,LOW);
    pinMode(AUDIO,INPUT); digitalWrite(AUDIO,LOW);
#endif
    mcu_init(&receiver); Serial.begin(9600);
#if APD_WATCHDOG_BOOTLOADER_VERIFIED
    wdt_enable(WDTO_2S);
#endif
}
void loop() {
    uint32_t now=millis(); mcu_tick(&receiver,now);
    /* Bounded byte work: don't starve timeout/display/watchdog on serial flood. */
    for(uint8_t n=0;n<32 && Serial.available()>0;++n) {
        if(mcu_feed(&receiver,(char)Serial.read(),now,reply,sizeof(reply))) Serial.print(reply);
    }
    for(uint8_t i=0;i<3;++i) {
        bool on=APD_INDICATORS_COMMISSIONED && mcu_indicator(&receiver,i,now);
        digitalWrite(INDICATORS[i],on?HIGH:LOW);
    }
    digitalWrite(FAULT_LED,mcu_fault(&receiver)?((now/250u)%2u?HIGH:LOW):LOW);
#if APD_ALARM_COMMISSIONED
    bool alarm=receiver.alarm_on && !mcu_fault(&receiver);
    digitalWrite(RELAY,alarm?(APD_RELAY_ACTIVE_HIGH?HIGH:LOW):(APD_RELAY_ACTIVE_HIGH?LOW:HIGH));
    if(alarm) tone(AUDIO,750); else {noTone(AUDIO); digitalWrite(AUDIO,LOW);}
#endif
#if APD_WATCHDOG_BOOTLOADER_VERIFIED
    wdt_reset();
#endif
}
