/**
 * 铜芯骏历 · 智能桌面信息日历
 * 硬件: ESP32-S3-RLCD-4.2
 * 屏幕: 4.2寸 RLCD (ST7305, 400x300)
 * 功能: 时间/温湿度/天气/节日/电量/灯带
 */

#include <Wire.h>
#include <U8g2lib.h>
#include <RTClib.h>
#include <SHTC3.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "time.h"

// ====== 用户配置 ======
const char* ssid = "你的WiFi名称";
const char* password = "你的WiFi密码";
const String WEATHER_API_KEY = "你的心知天气API密钥";
const String CITY = "hangzhou";

// ====== 引脚定义 ======
#define BATTERY_PIN 4
#define KEY_BUTTON 18
#define DHT22_PIN 15
#define LED_PIN 17
#define LED_COUNT 8

// ====== 屏幕初始化 (ST7305, 400x300) ======
U8G2_ST7305_400X300_1_4W_HW_SPI u8g2(U8G2_R0, /*cs=*/40, /*dc=*/5, /*reset=*/41);

// ====== 对象初始化 ======
RTC_PCF85063 rtc;
SHTC3 shtc3;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// ====== 全局变量 ======
String weatherToday = "";
String festivalToday = "";
float batteryPercent = 0;

// ====== 显示函数 ======
void updateDisplay(DateTime now, float temp, float humi) {
  u8g2.firstPage();
  do {
    // 第1行: 日期 (大号)
    u8g2.setFont(u8g2_font_logisoso32_tr);
    char dateStr[20];
    sprintf(dateStr, "%04d-%02d-%02d", now.year(), now.month(), now.day());
    u8g2.drawStr(10, 40, dateStr);
    
    // 第2行: 星期 + 时间
    u8g2.setFont(u8g2_font_ncenB18_tr);
    const char* weekdays[] = {"Sun","Mon","Tue","Wed","Thu","Fri","Sat"};
    u8g2.setCursor(10, 75);
    u8g2.print(weekdays[now.dayOfTheWeek()]);
    u8g2.setCursor(150, 75);
    char timeStr[10];
    sprintf(timeStr, "%02d:%02d:%02d", now.hour(), now.minute(), now.second());
    u8g2.print(timeStr);
    
    // 第3行: 温湿度
    u8g2.setFont(u8g2_font_ncenB12_tr);
    u8g2.setCursor(10, 110);
    u8g2.print("T:");
    u8g2.print(temp, 1);
    u8g2.print("C  H:");
    u8g2.print(humi, 0);
    u8g2.print("%");
    
    // 第4行: 天气 + 节日
    u8g2.setCursor(10, 140);
    if (weatherToday.length() > 0) u8g2.print(weatherToday);
    u8g2.setCursor(200, 140);
    if (festivalToday.length() > 0) u8g2.print(festivalToday);
    
    // 第5行: 电池电量
    u8g2.setCursor(10, 175);
    u8g2.print("Bat:");
    u8g2.print(batteryPercent, 0);
    u8g2.print("%");
    
  } while (u8g2.nextPage());
}

// ====== 初始化 ======
void setup() {
  Serial.begin(115200);
  
  // 屏幕初始化
  u8g2.begin();
  u8g2.setFontPosTop();
  
  // I2C总线 (GPIO13/14)[reference:60]
  Wire.begin(13, 14);
  
  // RTC初始化
  if (!rtc.begin()) { /* 错误处理 */ }
  
  // SHTC3初始化
  shtc3.begin();
  
  // 灯带初始化
  pixels.begin();
  pixels.setBrightness(30);
  pixels.clear();
  pixels.show();
  
  // 按键配置 (GPIO18, 内部上拉)[reference:61]
  pinMode(KEY_BUTTON, INPUT_PULLUP);
  
  // WiFi连接 + NTP同步
  WiFi.begin(ssid, password);
  // ... 等待连接
  configTime(8*3600, 0, "pool.ntp.org");
  // ... 同步到RTC
  
  // 首次获取天气和节日
  // ...
}

// ====== 主循环 ======
void loop() {
  DateTime now = rtc.now();
  
  // 读取温湿度
  float temp = shtc3.getTemperature();
  float humi = shtc3.getHumidity();
  
  // 读取电池电量
  batteryPercent = readBattery();
  
  // 按键检测 (下降沿触发)
  static int lastBtn = HIGH;
  int btn = digitalRead(KEY_BUTTON);
  if (lastBtn == HIGH && btn == LOW) {
    // 刷新天气
    weatherToday = getWeather();
  }
  lastBtn = btn;
  
  // 更新显示
  updateDisplay(now, temp, humi);
  
  // 灯带效果
  updateLED(now, temp);
  
  delay(1000);
}