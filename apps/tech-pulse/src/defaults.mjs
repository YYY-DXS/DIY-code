export const DEFAULT_CONFIG = {
  editionTime: "08:00",
  timezone: "Asia/Shanghai",
  enabled: true,
  lookbackHours: 30,
  maxNews: 7,
  maxDiy: 6,
  keywords: [
    "ESP32",
    "Arduino",
    "Raspberry Pi",
    "开源硬件",
    "机器人",
    "外骨骼",
    "航模",
    "3D打印",
    "航空",
    "DIY",
    "maker",
    "robotics",
    "hardware",
    "aerospace",
    "electric vehicle",
    "AI"
  ],
  sources: {
    rss: true,
    hackerNews: true,
    bilibili: true,
    github: true
  },
  rssFeeds: [
    {
      name: "Ars Technica",
      url: "https://feeds.arstechnica.com/arstechnica/index",
      weight: 0.88
    },
    {
      name: "The Verge",
      url: "https://www.theverge.com/rss/index.xml",
      weight: 0.82
    },
    {
      name: "TechCrunch",
      url: "https://techcrunch.com/feed/",
      weight: 0.78
    },
    {
      name: "IEEE Spectrum",
      url: "https://spectrum.ieee.org/feeds/feed.rss",
      weight: 0.92
    },
    {
      name: "IT之家",
      url: "https://www.ithome.com/rss/",
      weight: 0.84
    },
    {
      name: "少数派",
      url: "https://sspai.com/feed",
      weight: 0.76
    }
  ],
  bilibiliKeywords: ["科技 DIY", "ESP32", "开源硬件", "机器人 制作"],
  githubTopics: [
    "esp32",
    "arduino",
    "raspberry-pi",
    "diy",
    "hardware",
    "robotics",
    "3d-printing"
  ],
  delivery: {
    windowsToast: true,
    browserNotification: true,
    webhookUrl: "",
    serverChanKey: ""
  },
  weights: {
    freshness: 0.3,
    relevance: 0.24,
    engagement: 0.24,
    authority: 0.12,
    corroboration: 0.1
  }
};

export const SOURCE_LABELS = {
  rss: "科技媒体",
  hackerNews: "Hacker News",
  bilibili: "B站",
  github: "GitHub"
};
