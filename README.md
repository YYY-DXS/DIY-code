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
git clone git@github.com:YYY-DXS/DIY-code.git
git pull
git push
```

不想敲命令的话，双击 `tools\同步仓库.cmd`，它会自动拉取最新、提交本地改动并推送。

## 文件格式

仓库里只保留 Markdown 源文件。**Word 和 HTML 只是在本地生成给自己看的，不会上传**：

| 格式 | 用途 |
| --- | --- |
| `.md` | 仓库里唯一的格式，GitHub 上直接就能看 |
| `.html` | 本地生成，双击用浏览器打开，排版最舒服 |
| `.docx` | 本地生成，方便编辑和打印 |

改完 `.md` 之后在本地重新生成这两种：

```bash
python tools/md2readable/md_to_readable.py
```

## 许可

本项目采用 [MIT 许可](LICENSE)：任何人都可以自由使用、修改、再发布，
只要保留版权声明即可。
