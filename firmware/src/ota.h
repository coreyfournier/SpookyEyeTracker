#pragma once
#include <Arduino.h>

// Over-the-air updates: an HTTP endpoint the tracker (or scripts/ota_upload.py) POSTs a
// firmware .bin to. Enabled only when the build has an OTA_PASSWORD (scripts/wifi_env.py).
//
//   GET  /         -> {"id":"eye1","fw":"abc1234","board":"featheresp32","ota":true}
//   POST /update?board=<board id>   multipart body with the .bin, HTTP Basic auth eye:<password>
//        200 -> rebooting into the new firmware; 401 bad password; 409 wrong board; 500 flash error

void otaBegin();         // call once WiFi is up
void otaHandle();        // call every loop
bool otaEnabled();
bool otaActive();        // an upload is in progress (behaviour should pause)
int otaProgress();       // 0-100 while active
