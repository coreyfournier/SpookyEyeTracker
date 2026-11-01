#include "ota.h"
#include "build_info.h"
#include <Update.h>
#include <WebServer.h>
#include <WiFi.h>

#ifndef OTA_PASSWORD
#define OTA_PASSWORD ""
#endif

static WebServer server(80);
static bool started = false;
static bool active = false;
static bool rejected = false;     // current upload refused (auth / board) - ignore its data
static int rejectCode = 0;
static size_t total = 0, written = 0;

bool otaEnabled() { return OTA_PASSWORD[0] != 0; }
bool otaActive() { return active; }
int otaProgress() { return total ? (int)(written * 100 / total) : 0; }

static void handleInfo() {
  char body[160];
  snprintf(body, sizeof(body), "{\"id\":\"%s\",\"fw\":\"%s\",\"board\":\"%s\",\"ota\":%s}", EYE_NAME, FW_VERSION,
           FW_BOARD, otaEnabled() ? "true" : "false");
  server.send(200, "application/json", body);
}

static void handleUploadData() {
  HTTPUpload &up = server.upload();
  if (up.status == UPLOAD_FILE_START) {
    rejected = false;
    if (!server.authenticate("eye", OTA_PASSWORD)) {
      rejected = true, rejectCode = 401;
    } else if (server.arg("board") != FW_BOARD) {
      Serial.printf("ota: rejected image for board '%s' (this is %s)\n", server.arg("board").c_str(), FW_BOARD);
      rejected = true, rejectCode = 409;
    } else {
      total = server.header("Content-Length").toInt();
      written = 0;
      active = true;
      Serial.printf("ota: receiving %s\n", up.filename.c_str());
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
    }
  } else if (rejected) {
    return;
  } else if (up.status == UPLOAD_FILE_WRITE) {
    if (Update.write(up.buf, up.currentSize) != up.currentSize) Update.printError(Serial);
    written += up.currentSize;
  } else if (up.status == UPLOAD_FILE_END) {
    if (Update.end(true)) {
      Serial.printf("ota: %u bytes written, rebooting\n", (unsigned)up.totalSize);
    } else {
      Update.printError(Serial);
    }
  } else if (up.status == UPLOAD_FILE_ABORTED) {
    Update.abort();
    active = false;
  }
}

static void handleUploadDone() {
  if (rejected) {
    if (rejectCode == 401) return server.requestAuthentication();
    return server.send(409, "text/plain", "firmware is for a different board: this eye is " FW_BOARD);
  }
  if (Update.hasError() || !Update.isFinished()) {
    active = false;
    return server.send(500, "text/plain", String("update failed: ") + Update.errorString());
  }
  server.sendHeader("Connection", "close");
  server.send(200, "text/plain", "ok, rebooting");
  delay(300);
  ESP.restart();
}

void otaBegin() {
  if (started || !otaEnabled()) return;
  static const char *keep[] = {"Content-Length"};
  server.collectHeaders(keep, 1);
  server.on("/", HTTP_GET, handleInfo);
  server.on("/update", HTTP_POST, handleUploadDone, handleUploadData);
  server.begin();
  started = true;
  Serial.println("ota: listening on http port 80");
}

void otaHandle() {
  if (!started && WiFi.status() == WL_CONNECTED) otaBegin();
  if (started) server.handleClient();
}
