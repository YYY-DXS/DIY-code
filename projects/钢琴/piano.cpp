/*
 * ESP32 自动钢琴系统 - 最终完整版
 * 硬件：ESP32 + 2x PCA9685 + 24x 电磁铁 + MicroSD + OLED(SSD1306) + 4x4键盘
 * 功能：SD卡播放 + OLED显示 + 键盘本地WiFi配置
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <SD.h>
#include <MIDI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Keypad.h>
#include <WiFi.h>
#include <Preferences.h>

// -------------------- OLED 配置 --------------------
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDR 0x3C
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// -------------------- 4x4 矩阵键盘引脚 (使用GPIO) --------------------
const byte ROWS = 4;
const byte COLS = 4;
char keys[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};
byte rowPins[ROWS] = {13, 12, 14, 27};
byte colPins[COLS] = {26, 25, 33, 32};
Keypad keypad = Keypad( makeKeymap(keys), rowPins, colPins, ROWS, COLS );

// -------------------- WiFi 与 存储 --------------------
Preferences preferences;
const char* prefNamespace = "wifi-config";

// -------------------- 电磁铁 & SD卡 --------------------
Adafruit_PWMServoDriver pwm1 = Adafruit_PWMServoDriver(0x40);
Adafruit_PWMServoDriver pwm2 = Adafruit_PWMServoDriver(0x41);
MIDI_CREATE_INSTANCE(HardwareSerial, Serial, MIDI);
const int TOTAL_CHANNELS = 24;
const int STRIKE_DURATION = 80;
const int PWM_DUTY = 4095;
const int PWM_OFF = 0;
int noteToChannel[128];

File midiFile;
bool isPlaying = false;
bool isPaused = false;
uint32_t lastEventTime = 0;
uint32_t currentDeltaTime = 0;
uint8_t runningStatus = 0;
uint32_t trackLength = 0;
uint16_t ticksPerQuarter = 480;
float tempo = 500000; // 120 BPM

String playlist[50];
int playlistCount = 0;
int currentTrack = -1;
String currentTrackName = "无";

// -------------------- 初始化 --------------------
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // OLED初始化
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
  }
  display.display();
  delay(2000);
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(WHITE);
  display.setCursor(0, 24);
  display.println("自动钢琴");
  display.setTextSize(1);
  display.setCursor(0, 48);
  display.println("初始化中...");
  display.display();

  // 尝试自动连接已保存WiFi
  preferences.begin(prefNamespace, true);
  String ssid = preferences.getString("ssid", "");
  String pass = preferences.getString("password", "");
  preferences.end();
  if(ssid.length() > 0) {
    WiFi.begin(ssid.c_str(), pass.c_str());
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 20) {
      delay(500);
      tries++;
    }
  }

  // PCA9685初始化
  pwm1.begin(); pwm2.begin();
  pwm1.setPWMFreq(50); pwm2.setPWMFreq(50);
  for(int i=0; i<TOTAL_CHANNELS; i++) setPWM(i, PWM_OFF);

  // SD卡初始化
  if(!SD.begin(5)) {
    Serial.println("SD卡失败");
  } else {
    scanMidiFiles();
  }

  // 按键引脚 (内部上拉)
  pinMode(32, INPUT_PULLUP); // 播放/暂停 (实际按键需接GND)
  pinMode(33, INPUT_PULLUP); // 上一曲
  pinMode(34, INPUT);        // 下一曲，需外接10k上拉
  pinMode(35, INPUT);        // 停止，需外接10k上拉

  // 映射表
  for(int i=0; i<128; i++) noteToChannel[i] = -1;
  setupNoteMapping();

  MIDI.begin(MIDI_CHANNEL_OMNI);
  MIDI.turnThruOff();

  updateOLEDDisplay();
  Serial.println("系统就绪");
}

// -------------------- 主循环 --------------------
void loop() {
  // 键盘事件
  char key = keypad.getKey();
  if(key) {
    switch(key) {
      case 'A': // 播放/恢复
        if(!isPlaying && playlistCount>0) { currentTrack=0; playMidiFile(playlist[0]); }
        else if(isPaused) isPaused = false;
        break;
      case 'B': isPaused = true; break; // 暂停
      case 'C': // 停止
        isPlaying = false; isPaused = false;
        if(midiFile) midiFile.close();
        for(int i=0; i<TOTAL_CHANNELS; i++) setPWM(i, PWM_OFF);
        break;
      case 'D': nextTrack(); break; // 下一曲
      case '#': prevTrack(); break; // 上一曲
      case '*': displayWiFiConfigMenu(); updateOLEDDisplay(); break; // WiFi菜单
    }
  }

  // 处理串口命令（调试保留）
  if(Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if(cmd.startsWith("play ")) { playMidiFile(cmd.substring(5)); }
    else if(cmd == "stop") { /* ... */ }
    // 其他命令省略
  }

  // MIDI播放
  if(isPlaying && !isPaused) processMidiPlayback();

  // 定时刷新OLED
  static unsigned long lastUpdate = 0;
  if(millis() - lastUpdate > 5000) {
    updateOLEDDisplay();
    lastUpdate = millis();
  }

  // 按键检测（备用物理按键）
  if(digitalRead(32)==LOW) { /* 切换播放暂停 */ }
  // 其他按键处理省略...
}

// -------------------- OLED 显示 --------------------
void updateOLEDDisplay() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);
  display.setCursor(0,0);
  if(WiFi.status()==WL_CONNECTED) { display.print("WiFi:"); display.println(WiFi.SSID()); }
  else { display.println("WiFi:未连接"); }
  
  display.setCursor(0,16);
  display.print(isPlaying ? (isPaused?"⏸":"▶") : "⏹");
  display.println(currentTrackName);
  
  display.setCursor(0,32);
  display.print("*键 配置网络");
  display.setCursor(0,48);
  display.print("A播放 B暂停 C停止 D下一曲");
  display.display();
}

// -------------------- WiFi 配置菜单 --------------------
void displayWiFiConfigMenu() {
  display.clearDisplay();
  display.setCursor(0,0);
  display.println("WiFi 配置");
  display.println("A:扫描网络");
  display.println("B:清除配置");
  display.println("C:返回");
  display.display();
  
  char key = keypad.waitForKey();
  if(key == 'A') scanAndConnectWiFi();
  else if(key == 'B') { preferences.clear(); ESP.restart(); }
}

void scanAndConnectWiFi() {
  display.clearDisplay(); display.setCursor(0,0); display.println("扫描中..."); display.display();
  int n = WiFi.scanNetworks();
  int idx = 0;
  while(1) {
    display.clearDisplay(); display.setCursor(0,0);
    display.print(n); display.println(" 个网络");
    for(int i=0; i<min(5,n); i++) {
      if(i==idx%5) display.print(">");
      else display.print(" ");
      display.println(WiFi.SSID(i));
    }
    display.println("A连接 B翻页 C退出");
    display.display();
    char k = keypad.waitForKey();
    if(k=='A') {
      String pw = inputWiFiPassword();
      if(connectToWiFi(WiFi.SSID(idx), pw)) {
        preferences.begin(prefNamespace, false);
        preferences.putString("ssid", WiFi.SSID(idx));
        preferences.putString("password", pw);
        preferences.end();
        break;
      }
    } else if(k=='B') idx += 5; else if(k=='C') return;
  }
}

String inputWiFiPassword() {
  String pw = "";
  while(1) {
    char k = keypad.getKey();
    if(k) {
      if(k=='A') break;
      else if(k=='B' && pw.length()>0) pw.remove(pw.length()-1);
      else pw += k;
    }
    display.clearDisplay(); display.setCursor(0,0); display.println("密码:"); display.println(pw); display.display();
    delay(50);
  }
  return pw;
}

bool connectToWiFi(String ssid, String pass) {
  WiFi.begin(ssid.c_str(), pass.c_str());
  int cnt=0; while(WiFi.status()!=WL_CONNECTED && cnt<20) { delay(500); cnt++; }
  return WiFi.status()==WL_CONNECTED;
}

// -------------------- 音符映射 (24键) --------------------
void setupNoteMapping() {
  // C3 octave (12 keys)
  noteToChannel[48]=0; noteToChannel[50]=1; noteToChannel[52]=2; noteToChannel[53]=3;
  noteToChannel[55]=4; noteToChannel[57]=5; noteToChannel[59]=6;
  noteToChannel[49]=7; noteToChannel[51]=8; noteToChannel[54]=9; noteToChannel[56]=10; noteToChannel[58]=11;
  // C4 octave (12 keys)
  noteToChannel[60]=12; noteToChannel[62]=13; noteToChannel[64]=14; noteToChannel[65]=15;
  noteToChannel[67]=16; noteToChannel[69]=17; noteToChannel[71]=18;
  noteToChannel[61]=19; noteToChannel[63]=20; noteToChannel[66]=21; noteToChannel[68]=22; noteToChannel[70]=23;
}

// -------------------- PWM控制 --------------------
void setPWM(int ch, int duty) {
  if(ch<16) pwm1.setPWM(ch,0,duty);
  else if(ch<32) pwm2.setPWM(ch-16,0,duty);
}

// -------------------- SD卡文件扫描 --------------------
void scanMidiFiles() {
  File root = SD.open("/");
  playlistCount = 0;
  while(true) {
    File entry = root.openNextFile();
    if(!entry) break;
    String name = entry.name();
    if(!entry.isDirectory() && (name.endsWith(".mid")||name.endsWith(".MID"))) {
      playlist[playlistCount++] = name;
    }
    entry.close();
  }
  root.close();
}

// -------------------- MIDI文件播放 --------------------
void playMidiFile(String filename) {
  if(midiFile) midiFile.close();
  if(!filename.startsWith("/")) filename = "/"+filename;
  midiFile = SD.open(filename);
  if(!midiFile) return;
  if(!parseMidiHeader()) { midiFile.close(); return; }
  isPlaying = true; isPaused = false;
  currentTrackName = filename;
  lastEventTime = millis();
  currentDeltaTime = 0;
  runningStatus = 0;
  tempo = 500000;
}

bool parseMidiHeader() {
  uint8_t hdr[14]; if(midiFile.read(hdr,14)!=14) return false;
  if(hdr[0]!='M'||hdr[1]!='T'||hdr[2]!='h'||hdr[3]!='d') return false;
  uint16_t div = (hdr[12]<<8)|hdr[13];
  ticksPerQuarter = (div&0x8000)?480:div;
  while(midiFile.available()) {
    if(midiFile.peek()=='M') {
      uint8_t buf[4]; midiFile.read(buf,4);
      if(buf[0]=='M'&&buf[1]=='T'&&buf[2]=='r'&&buf[3]=='k') {
        uint8_t len[4]; midiFile.read(len,4);
        trackLength = (len[0]<<24)|(len[1]<<16)|(len[2]<<8)|len[3];
        return true;
      } else midiFile.seek(midiFile.position()-3);
    }
    midiFile.read();
  }
  return false;
}

uint32_t readVarLen() {
  uint32_t v=0; uint8_t c;
  for(int i=0;i<4;i++) { c=midiFile.read(); v=(v<<7)|(c&0x7F); if(!(c&0x80)) break; }
  return v;
}

void processMidiPlayback() {
  if(!midiFile||!midiFile.available()) { midiFile.close(); isPlaying=false; nextTrack(); return; }
  if(currentDeltaTime>0) {
    if(millis()-lastEventTime >= currentDeltaTime) currentDeltaTime=0;
    else return;
  }
  if(trackLength==0) { currentDeltaTime=1000; return; }
  uint32_t delta = readVarLen();
  uint8_t event = midiFile.read(); trackLength--;
  if(event==0xFF) {
    uint8_t meta = midiFile.read(); trackLength--;
    uint32_t len = readVarLen();
    if(meta==0x2F) { trackLength=0; return; }
    else if(meta==0x51 && len==3) {
      uint8_t t[3]; midiFile.read(t,3); tempo = (t[0]<<16)|(t[1]<<8)|t[2]; trackLength-=3;
    } else { midiFile.seek(midiFile.position()+len); trackLength-=len; }
  } else if(event==0xF0||event==0xF7) {
    uint32_t len = readVarLen(); midiFile.seek(midiFile.position()+len); trackLength-=len;
  } else {
    uint8_t status = event;
    if(status<0x80) { status=runningStatus; midiFile.seek(midiFile.position()-1); }
    else runningStatus=status;
    uint8_t hi = status&0xF0;
    if(hi==0x90||hi==0x80) {
      uint8_t note = midiFile.read(); uint8_t vel = midiFile.read(); trackLength-=2;
      int ch = noteToChannel[note];
      if(ch>=0 && hi==0x90 && vel>0) { setPWM(ch,PWM_DUTY); delay(STRIKE_DURATION); setPWM(ch,PWM_OFF); }
    } else if(hi==0xC0||hi==0xD0) { midiFile.read(); trackLength--; }
    else { midiFile.read(); midiFile.read(); trackLength-=2; }
  }
  float msPerTick = tempo/1000.0/ticksPerQuarter;
  currentDeltaTime = delta * msPerTick;
  lastEventTime = millis();
}

void nextTrack() {
  if(playlistCount==0) return;
  currentTrack = (currentTrack+1)%playlistCount;
  playMidiFile(playlist[currentTrack]);
}

void prevTrack() {
  if(playlistCount==0) return;
  currentTrack = (currentTrack-1+playlistCount)%playlistCount;
  playMidiFile(playlist[currentTrack]);
}