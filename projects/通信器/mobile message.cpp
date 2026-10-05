/*
 * 中文直聊折叠通信器 · 旗舰版
 * 硬件：LILYGO T-Deck (ESP32-S3, SX1262, 2.8"触摸屏, QWERTY键盘)
 * 功能：双模动态切换（ESP-NOW + LoRa）、离线拼音输入、智能联想、群聊、隐秘提醒
 */

#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <RadioLib.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <PCF8574.h>
#include <LittleFS.h>
#include <vector>

// ==================== 硬件引脚定义 (基于 LILYGO T-Deck) ====================
// 屏幕 (SPI)
#define TFT_SCK  12
#define TFT_MOSI 11
#define TFT_CS   10
#define TFT_DC   13
#define TFT_RST  14
// I2C (键盘与触摸屏共用)
#define I2C_SDA  17
#define I2C_SCL  18
// LoRa 模块 (SX1262)
#define LORA_NSS  8
#define LORA_DIO1 9
#define LORA_BUSY 5
#define LORA_RST  6
#define LORA_SCK  12  // 与屏幕共用 SPI
#define LORA_MOSI 11
#define LORA_MISO 7
// 提醒 LED
#define LED_PIN   15

// ==================== 通信参数 ====================
#define DEVICE_NAME "我的T-Deck"
#define MAX_MESSAGE_LEN 1024
#define ESP_NOW_CHUNK_SIZE 220
#define LORA_CHUNK_SIZE 200
#define HEARTBEAT_INTERVAL 3000
#define RSSI_THRESHOLD -80
#define HEARTBEAT_MISS_MAX 4

enum CommMode { MODE_ESPNOW, MODE_LORA };
CommMode currentMode = MODE_ESPNOW;

enum MsgType { MSG_CHAT_LONG, MSG_CHAT_SHORT, MSG_GPS, MSG_STATUS, MSG_CMD };

// ==================== 全局对象 ====================
U8G2_ST7789_280X320_1_4W_SW_SPI u8g2(U8G2_R1, TFT_SCK, TFT_MOSI, TFT_CS, TFT_DC, TFT_RST);
PCF8574 pcf8574(0x27, I2C_SDA, I2C_SCL);
SX1262 lora = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY);

String pinyin_input = "";
String final_text = "";
String candidate_str = "";
bool candidate_mode = false;

#define MAX_FREQ_WORDS 200
struct FreqWord { String word; int count; };
FreqWord freq_words[MAX_FREQ_WORDS];
int freq_word_count = 0;

#define MAX_CONTACTS 10
String contact_names[MAX_CONTACTS];
uint8_t contact_macs[MAX_CONTACTS][6];
int contact_count = 0;
int current_contact = -1;

String received_message = "";
bool msg_received = false;
bool has_unread = false;
String status_line = "就绪";
bool is_group_chat = false;
bool is_scanning = false;
unsigned long scan_start = 0;

uint8_t peer_mac[6];
bool espnow_ok = false;
bool lora_ok = false;
unsigned long last_heartbeat_sent = 0;
unsigned long last_heartbeat_recv = 0;
unsigned int missed_heartbeats = 0;
int current_rssi = -100;

// ==================== 词库相关 ====================
bool dict_loaded = false;
bool loadPinyinDict() {
  // 详细实现请参考项目 GitHub 仓库
  return false;
}
String getCandidatesFromDict(String pinyin) {
  // 二分查找 LittleFS 中的词库
  return pinyin;
}

// ==================== 内部函数声明 ====================
void initDisplay();
void initKeyboard();
void initLoRa();
void initESPNow();
void sendHeartbeat();
void checkLinkHealth();
void switchToLoRa();
void switchToESPNOW();
void sendMessage(MsgType type, String msg);
void sendViaESPNOW(String data);
void sendViaLoRa(String data);
void handleReceivedESPNOW(const uint8_t *mac, const uint8_t *data, int len);
void handleReceivedLoRa(String payload);
String getCandidates(String pinyin);
void recordWord(String word);
String getSuggestions(String prefix);
void drawUI();
void handleKeyboard();
char scanKeyboard();

// ==================== 初始化 ====================
void setup() {
  Serial.begin(115200);
  initDisplay();
  Wire.begin(I2C_SDA, I2C_SCL);
  pcf8574.begin();
  LittleFS.begin(true);
  loadPinyinDict();
  initLoRa();
  initESPNow();
  uint8_t self_mac[6];
  esp_read_mac(self_mac, ESP_MAC_WIFI_STA);
  contact_names[0] = DEVICE_NAME;
  memcpy(contact_macs[0], self_mac, 6);
  contact_count = 1;
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(20, 50, "折叠通信器·旗舰版");
  u8g2.sendBuffer();
  delay(1500);
  drawUI();
}

void loop() {
  handleKeyboard();
  sendHeartbeat();
  checkLinkHealth();
  if (lora_ok) {
    int packetSize = lora.getPacketLength();
    if (packetSize > 0) {
      String str = "";
      while (lora.available()) str += (char)lora.read();
      handleReceivedLoRa(str);
    }
  }
  if (is_scanning && millis() - scan_start > 10000) {
    is_scanning = false;
    status_line = "扫描完成";
  }
  drawUI();
  delay(30);
}

// ==================== 显示初始化 ====================
void initDisplay() {
  u8g2.begin();
  u8g2.setContrast(255);
  u8g2.setFont(u8g2_font_6x10_tf);
}

// ==================== 键盘扫描（占位，需根据实际矩阵实现）====================
char scanKeyboard() {
  // 读取 PCF8574 端口状态并解析按键码
  return 0;
}

// ==================== 键盘处理（同之前版本）====================
void handleKeyboard() {
  char c = scanKeyboard();
  if (!c) return;
  // … 省略，与前述代码逻辑相同
}

// ==================== 候选字获取（兜底内置词库）====================
String getCandidates(String pinyin) {
  if (dict_loaded) return getCandidatesFromDict(pinyin);
  if (pinyin == "ni") return "你泥拟尼";
  if (pinyin == "hao") return "好号毫浩";
  // 可继续扩展常用字
  return pinyin;
}

// ==================== 词频统计 ====================
void recordWord(String word) { /* 同前 */ }
String getSuggestions(String prefix) { /* 同前 */ }

// ==================== 双模通信 ====================
void initLoRa() {
  SPI.setPins(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = lora.begin(915.0);
  if (state == RADIOLIB_ERR_NONE) {
    lora.setSpreadingFactor(9);
    lora.setBandwidth(125.0);
    lora.setOutputPower(22);
    lora_ok = true;
  }
}

void initESPNow() { /* 同前 */ }
void sendHeartbeat() { /* 同前 */ }
void checkLinkHealth() { /* 同前 */ }
void switchToLoRa() { currentMode = MODE_LORA; status_line = "[LoRa] 弱信号"; }
void switchToESPNOW() { currentMode = MODE_ESPNOW; status_line = "[ESP-NOW] 强信号"; }

void sendMessage(MsgType type, String msg) {
  if (type == MSG_CHAT_LONG && currentMode == MODE_ESPNOW)
    sendViaESPNOW(msg);
  else
    sendViaLoRa(msg);
}

void sendViaESPNOW(String data) { /* 同前：分包发送 */ }
void sendViaLoRa(String data) { lora.startTransmit(data); }

void handleReceivedESPNOW(const uint8_t *mac, const uint8_t *data, int len) { /* 同前 */ }
void handleReceivedLoRa(String payload) { /* 同前 */ }

// ==================== 界面绘制 ====================
void drawUI() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  String modeStr = (currentMode == MODE_ESPNOW) ? "[E]" : "[L]";
  modeStr += is_group_chat ? "群" : "私";
  u8g2.drawStr(0, 10, (modeStr + " " + status_line).c_str());
  if (has_unread && !msg_received) u8g2.drawCircle(310, 8, 2);
  if (msg_received) {
    u8g2.drawStr(0, 30, received_message.c_str());
    u8g2.drawStr(0, 60, "按Esc返回");
  } else {
    u8g2.setCursor(0, 30);
    if (candidate_mode) {
      u8g2.print("候选: "); u8g2.print(candidate_str);
    } else {
      u8g2.print("拼音: "); u8g2.print(pinyin_input);
      u8g2.setCursor(0, 45);
      u8g2.print("内容: "); u8g2.print(final_text);
    }
    u8g2.setCursor(0, 60);
    if (is_group_chat) u8g2.print("发送至: [群聊]");
    else if (current_contact >= 0) u8g2.print("发送至: " + contact_names[current_contact]);
    else u8g2.print("按Esc扫描设备");
    if (pinyin_input.length() >= 2 && !candidate_mode) {
      String sug = getSuggestions(pinyin_input);
      if (sug.length()) {
        u8g2.setCursor(0, 75);
        u8g2.print("联想: " + sug);
      }
    }
  }
  u8g2.sendBuffer();
}