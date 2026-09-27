# DIY-

个人 DIY 项目仓库。

## 这里面放什么

- 自己动手做的项目资料（模型、硬件、手工等）
- 和项目配套的小工具、脚本

## 目录

| 目录 | 说明 |
| --- | --- |
| [`projects/`](projects/README.md) | 各个 DIY 项目的资料（齐柏林飞艇、外骨骼、台历、航模方向） |
| [`tools/`](tools/README.md) | 配套工具：DeepSeek 记录同步、Git 同步脚本 |

## 同步方式

本机已经配好 SSH 密钥，可以直接拉取和推送：

```bash
git clone git@github.com:YYY-DXS/DIY-.git
git pull
git push
```

不想敲命令的话，双击 `tools\同步仓库.cmd`，它会自动拉取最新、提交本地改动并推送。
